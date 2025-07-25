# Copyright (c) OpenMMLab. All rights reserved.
import dataclasses
import json
import uuid
from abc import abstractmethod
from typing import List, Literal, Optional, Union

from mmengine import Registry

from lmdeploy.utils import get_logger

logger = get_logger('lmdeploy')
MODELS = Registry('model', locations=['lmdeploy.model'])


def random_uuid() -> str:
    """Return a random uuid."""
    return str(uuid.uuid4().hex)


def get_text(content: Union[str, List[dict]]):
    """Within the OpenAI API, the content field may be specified as either a
    string or a list of ChatCompletionContentPartTextParam (defined in openai).

    When a list is provided, lmdeploy selects the first element to incorporate into the chat template, as the manner in
    which OpenAI processes lists is not explicitly defined.
    """

    if isinstance(content, str):
        return content
    return content[0]['text']


@dataclasses.dataclass
class ChatTemplateConfig:
    """Parameters for chat template.

    Args:
        model_name (str): the name of the deployed model. Determine which chat template will be applied.
            All the chat template names: `lmdeploy list`
        system (str | None): begin of the system prompt
        meta_instruction (str | None): system prompt
        eosys (str | None): end of the system prompt
        user (str | None): begin of the user prompt
        eoh (str | None): end of the user prompt
        assistant (str | None): begin of the assistant prompt
        eoa (str | None): end of the assistant prompt
        tool (str | None): begin of the tool prompt
        eotool (str | None): end of the tool prompt
        capability: ('completion' | 'infilling' | 'chat' | 'python') = None
    """  # noqa: E501

    model_name: str
    system: Optional[str] = None
    meta_instruction: Optional[str] = None
    eosys: Optional[str] = None
    user: Optional[str] = None
    eoh: Optional[str] = None
    assistant: Optional[str] = None
    eoa: Optional[str] = None
    tool: Optional[str] = None
    eotool: Optional[str] = None
    separator: Optional[str] = None
    capability: Optional[Literal['completion', 'infilling', 'chat', 'python']] = None
    stop_words: Optional[List[str]] = None

    @property
    def chat_template(self):
        attrs = {key: value for key, value in dataclasses.asdict(self).items() if value is not None}
        attrs.pop('model_name', None)
        if self.model_name in MODELS.module_dict.keys():
            model: BaseModel = MODELS.get(self.model_name)(**attrs)
        else:
            logger.warning(f'Could not find {self.model_name} in registered models. '
                           f'Register {self.model_name} using the BaseChatTemplate.')
            model = BaseChatTemplate(**attrs)
        return model

    def to_json(self, file_path=None):
        """Convert the dataclass instance to a JSON formatted string and
        optionally save to a file."""
        json_str = json.dumps(dataclasses.asdict(self), ensure_ascii=False, indent=4)
        if file_path:
            with open(file_path, 'w', encoding='utf-8') as file:
                file.write(json_str)
        return json_str

    @classmethod
    def from_json(cls, file_or_string):
        """Construct a dataclass instance from a JSON file or JSON string."""
        try:
            # Try to open the input_data as a file path
            with open(file_or_string, 'r', encoding='utf-8') as file:
                json_data = file.read()
        except FileNotFoundError:
            # If it's not a file path, assume it's a JSON string
            json_data = file_or_string
        except IOError:
            # If it's not a file path and not a valid JSON string, raise error
            raise ValueError('Invalid input. Must be a file path or a valid JSON string.')
        json_data = json.loads(json_data)
        if json_data.get('model_name', None) is None:
            json_data['model_name'] = random_uuid()
        if json_data['model_name'] not in MODELS.module_dict.keys():
            MODELS.register_module(json_data['model_name'], module=BaseChatTemplate)
        return cls(**json_data)


@MODELS.register_module(name='llama')
@MODELS.register_module(name='base')
class BaseModel:
    """Base model."""

    def __init__(self, capability='chat', stop_words=None, **kwargs):
        self.stop_words = stop_words
        self.capability = capability

    def get_prompt(self, prompt, sequence_start=True):
        """Return the prompt that is concatenated with other elements in the
        chat template.

        Args:
            prompt (str): user's input prompt
            sequence_start (bool): indicator for the first round chat of a
               session sequence
        Returns:
            str: the concatenated prompt
        """
        return prompt

    @abstractmethod
    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        """Return the prompt that is concatenated with other elements in the
        chat template. When messages arg is a string, return
        self.get_prompt(messages). When messages arg is a chat history, return
        translated prompt from chat history.

        Args:
            messages (str | List): user's input prompt
        Returns:
            str: the concatenated prompt
        """
        if isinstance(messages, str):
            return self.get_prompt(messages)
        # chat history processing in derived classes

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        return None


class BaseChatTemplate(BaseModel):
    """Base Chat template."""

    def __init__(self,
                 system='',
                 meta_instruction='',
                 eosys='',
                 user='',
                 eoh='',
                 assistant='',
                 eoa='',
                 separator='',
                 tool='',
                 eotool='',
                 **kwargs):
        super().__init__(**kwargs)
        self.system = system
        self.meta_instruction = meta_instruction
        self.user = user
        self.eoh = eoh
        self.eoa = eoa
        self.separator = separator
        self.eosys = eosys
        self.assistant = assistant
        self.tool = tool
        self.eotool = eotool

    def get_prompt(self, prompt, sequence_start=True):
        """Return the prompt that is concatenated with other elements in the
        chat template.

        Args:
            prompt (str): user's input prompt
            sequence_start (bool): indicator for the first round chat of a
               session sequence
        Returns:
            str: the concatenated prompt
        """
        if self.capability == 'completion':
            return prompt
        if sequence_start:
            # None is different from ''
            if self.meta_instruction is not None:
                return f'{self.system}{self.meta_instruction}{self.eosys}' \
                    f'{self.user}{prompt}{self.eoh}' \
                    f'{self.assistant}'
            else:
                return f'{self.user}{prompt}{self.eoh}' \
                       f'{self.assistant}'
        else:
            return f'{self.separator}{self.user}{prompt}{self.eoh}' \
                   f'{self.assistant}'

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        """Return the prompt that is concatenated with other elements in the
        chat template.

        Args:
            messages (str | List): user's input prompt
        Returns:
            str: the concatenated prompt
        """
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        box_map = dict(user=self.user, assistant=self.assistant, system=self.system, tool=self.tool)
        eox_map = dict(user=self.eoh, assistant=self.eoa + self.separator, system=self.eosys, tool=self.eotool)
        ret = ''
        if self.meta_instruction is not None and sequence_start:
            if len(messages) and messages[0]['role'] != 'system':
                ret += f'{self.system}{self.meta_instruction}{self.eosys}'
        for message in messages:
            role = message['role']
            content = get_text(message['content'])
            ret += f'{box_map[role]}{content}{eox_map[role]}'
        if len(messages) and messages[-1]['role'] == 'assistant' and len(eox_map['assistant']) > 0:
            return ret[:-len(eox_map['assistant'])]  # prefix of response
        ret += f'{self.assistant}'
        return ret


@MODELS.register_module(name=['deepseek-v3'])
class DeepseekV3(BaseChatTemplate):

    def __init__(self, user='<｜User｜>', assistant='<｜Assistant｜>', eoa='<｜end▁of▁sentence｜>', **kwargs):
        super().__init__(user=user, assistant=assistant, eoa=eoa, **kwargs)

    def get_prompt(self, prompt, sequence_start=True):
        if sequence_start:
            return '<｜begin▁of▁sentence｜>' + super().get_prompt(prompt, sequence_start)
        return super().get_prompt(prompt, sequence_start)

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        if sequence_start and not isinstance(messages, str):
            return '<｜begin▁of▁sentence｜>' + super().messages2prompt(messages, sequence_start, **kwargs)
        return super().messages2prompt(messages, sequence_start, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'deepseek-v3' in path:
            return 'deepseek-v3'


@MODELS.register_module(name=['deepseek-r1'])
class DeepseekR1(DeepseekV3):

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        if sequence_start and not isinstance(messages, str):
            return super().messages2prompt(messages, sequence_start, **kwargs) + '<think>\n'
        return super().messages2prompt(messages, sequence_start, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'deepseek-r1' in path:
            return 'deepseek-r1'


@MODELS.register_module(name='cogvlm')
class CogVLM(BaseChatTemplate):
    """Chat template of CogVLM model."""

    def __init__(self,
                 meta_instruction='',
                 eosys='',
                 user='Question: ',
                 separator='\n',
                 eoh=' ',
                 assistant='Answer:',
                 eoa='</s>',
                 stop_words=['</s>'],
                 **kwargs):
        super().__init__(meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         separator=separator,
                         assistant=assistant,
                         eoa=eoa,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'cogvlm' in path and 'cogvlm2' not in path:
            return 'cogvlm'


@MODELS.register_module(name='cogvlm2')
class CogVLM2(CogVLM):
    """Chat template of CogVLM2 model."""

    def __init__(self, eoa='<|end_of_text|>', stop_words=['<|end_of_text|>'], **kwargs):
        super().__init__(eoa=eoa, stop_words=stop_words, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'cogvlm2' in path:
            return 'cogvlm2'


@MODELS.register_module(name='wizardlm')
@MODELS.register_module(name='vicuna')
class Vicuna(BaseChatTemplate):
    """Chat template of vicuna model."""

    def __init__(
            self,
            meta_instruction="""A chat between a curious user and an artificial intelligence assistant. The assistant gives helpful, detailed, and polite answers to the user's questions.""",  # noqa: E501
            eosys=' ',
            user='USER: ',
            eoh=' ',
            assistant='ASSISTANT: ',
            eoa='</s>',
            stop_words=['</s>'],
            **kwargs):
        super().__init__(meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         stop_words=stop_words,
                         **kwargs)

    def get_prompt(self, prompt, sequence_start=True):
        if self.capability == 'chat':
            return super().get_prompt(prompt, sequence_start)[:-1]
        return super().get_prompt(prompt, sequence_start)

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        return super().messages2prompt(messages, sequence_start, **kwargs)[:-1]

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'vicuna' in path and 'llava' not in path:
            return 'vicuna'
        if 'wizardlm' in path:
            return 'wizardlm'


@MODELS.register_module(name='llava-v1')
class Llavav1(Vicuna):
    """Chat template of llava-v1 model."""

    def __init__(
            self,
            meta_instruction="""A chat between a curious human and an artificial intelligence assistant. The assistant gives helpful, detailed, and polite answers to the human's questions.""",  # noqa: E501
            **kwargs):
        super().__init__(meta_instruction=meta_instruction, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'llava' in path and 'v1' in path and 'v1.6-34b' not in path \
                and 'mistral' not in path:
            return 'llava-v1'
        elif 'llava-1.5' in path:
            return 'llava-v1'


@MODELS.register_module(name='internlm')
class InternLMChat7B(BaseChatTemplate):
    """Chat template of InternLM model."""

    def __init__(
            self,
            system='<|System|>:',
            meta_instruction="""You are an AI assistant whose name is InternLM (书生·浦语).
- InternLM (书生·浦语) is a conversational language model that is developed by Shanghai AI Laboratory (上海人工智能实验室). It is designed to be helpful, honest, and harmless.
- InternLM (书生·浦语) can understand and communicate fluently in the language chosen by the user such as English and 中文.
""",  # noqa: E501
            eosys='\n',
            user='<|User|>:',
            eoh='\n',
            assistant='<|Bot|>:',
            eoa='<eoa>',
            separator='\n',
            stop_words=['<eoa>'],
            **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if all([c not in path for c in ['internlm3', 'internlm2', '8k']]) and \
                all([c in path for c in ['internlm', 'chat']]):
            return 'internlm'


@MODELS.register_module(name='internlm3')
@MODELS.register_module(name='internlm2')
class InternLM2Chat7B(InternLMChat7B):
    """Chat template and generation parameters of InternLM2-Chat-7B."""

    def __init__(self,
                 system='<|im_start|>system\n',
                 user='<|im_start|>user\n',
                 assistant='<|im_start|>assistant\n',
                 environment='<|im_start|>environment\n',
                 plugin='<|plugin|>',
                 interpreter='<|interpreter|>',
                 eosys='<|im_end|>\n',
                 eoh='<|im_end|>\n',
                 eoa='<|im_end|>',
                 eoenv='<|im_end|>\n',
                 separator='\n',
                 stop_words=['<|im_end|>', '<|action_end|>'],
                 **kwargs):
        self.plugin = plugin
        self.interpreter = interpreter
        self.environment = environment
        self.eoenv = eoenv
        super(InternLM2Chat7B, self).__init__(system=system,
                                              user=user,
                                              assistant=assistant,
                                              eosys=eosys,
                                              eoh=eoh,
                                              eoa=eoa,
                                              separator=separator,
                                              stop_words=stop_words,
                                              **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'internlm2' in path and ('chat' in path or 'math' in path):
            return 'internlm2'

        if 'internlm3' in path and ('instruct' in path):
            return 'internlm3'

    def messages2prompt(self, messages, sequence_start=True, tools=None, **kwargs):
        """Return the prompt that is concatenated with other elements in the
        chat template.

        Args:
            messages (str | List): user's input prompt
        Returns:
            str: the concatenated prompt
        """
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        box_map = dict(user=self.user,
                       assistant=self.assistant,
                       system=self.system,
                       environment=self.environment,
                       tool=self.environment)
        eox_map = dict(user=self.eoh,
                       assistant=self.eoa + self.separator,
                       system=self.eosys,
                       environment=self.eoenv,
                       tool=self.eoenv)
        name_map = dict(plugin=self.plugin, interpreter=self.interpreter)
        ret = ''
        if self.meta_instruction is not None and sequence_start:
            if len(messages) and messages[0]['role'] != 'system':
                ret += f'{self.system}{self.meta_instruction}{self.eosys}'

        if tools:
            tools_prompt = dict(
                role='system',
                name='plugin',  # only support internlm2
                content=json.dumps(tools, ensure_ascii=False))
            insert_index = 0
            if messages[0]['role'] == 'system':
                insert_index = 1
            messages.insert(insert_index, tools_prompt)
        for message in messages:
            role = message['role']
            content = get_text(message['content'])
            if role == 'assistant' and message.get('tool_calls', None) is not None:
                for tool_call in message['tool_calls']:
                    function = tool_call.get('function', {})
                    function['name'] = function.get('name', '')
                    function['parameters'] = function.get('parameters', function.get('arguments', ''))
                    function.pop('arguments')
                    if isinstance(function['parameters'], str):
                        function['parameters'] = json.loads(function['parameters'])
                    content += f'<|action_start|><|plugin|>\n{json.dumps(function, ensure_ascii=False)}<|action_end|>'
            if 'name' in message and message['name'] in name_map:
                begin = box_map[role].strip() + f" name={name_map[message['name']]}\n"
            else:
                begin = box_map[role]
            ret += f'{begin}{content}{eox_map[role]}'
        if len(messages) and messages[-1]['role'] == 'assistant':
            return ret[:-len(eox_map['assistant'])]  # prefix of response
        ret += f'{self.assistant}'
        return ret


@MODELS.register_module(name='internvl-internlm2')
class InternVLInternLM2Chat(InternLM2Chat7B):

    def __init__(self, meta_instruction='You are an AI assistant whose name is InternLM (书生·浦语).', **kwargs):
        super().__init__(meta_instruction=meta_instruction, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'internvl' in path and 'v1-5' in path:
            if 'mini' in path and '4b' in path:
                # use internvl-phi3 template
                return None
            return 'internvl-internlm2'

        if 'chemvlm' in path:
            return 'internvl-internlm2'


@MODELS.register_module(name='internvl2-internlm2')
class InternVL2InternLM2(InternLM2Chat7B):

    def __init__(self,
                 meta_instruction='你是由上海人工智能实验室联合商汤科技开发的书生多模态大模型，英文名叫InternVL, 是一个有用无害的人工智能助手。',
                 eosys='<|im_end|>',
                 eoh='<|im_end|>',
                 separator='',
                 stop_words=['<|im_start|>', '<|im_end|>'],
                 **kwargs):
        super().__init__(meta_instruction=meta_instruction,
                         eosys=eosys,
                         separator=separator,
                         eoh=eoh,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if ('internvl2' in path and 'internvl2-4b' not in path) or 'mono-internvl' in path:
            if 'internvl2.5' in path or 'internvl2_5' in path:
                return None
            return 'internvl2-internlm2'


@MODELS.register_module(name='internvl2_5')
class InternVL2_5(InternLM2Chat7B):

    def __init__(
            self,
            meta_instruction='你是书生·万象，英文名是InternVL，是由上海人工智能实验室、清华大学及多家合作单位联合开发的多模态大语言模型。',  # noqa
            **kwargs):
        super().__init__(meta_instruction=meta_instruction, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'internvl2.5' in path or 'internvl2_5' in path or 'internvl3' in path:
            return 'internvl2_5'


@MODELS.register_module(name=['internlm-xcomposer2', 'internlm-xcomposer2d5'])
class InternLMXComposer2Chat7B(InternLMChat7B):
    """Chat template and generation parameters of InternLM-XComposer2-7b."""

    def __init__(
            self,
            system='[UNUSED_TOKEN_146]system\n',
            meta_instruction="""You are an AI assistant whose name is InternLM-XComposer (浦语·灵笔).
- InternLM-XComposer (浦语·灵笔) is a multi-modality conversational language model that is developed by Shanghai AI Laboratory (上海人工智能实验室). It is designed to be helpful, honest, and harmless.
- InternLM-XComposer (浦语·灵笔) can understand and communicate fluently in the language chosen by the user such as English and 中文.
- InternLM-XComposer (浦语·灵笔) is capable of comprehending and articulating responses effectively based on the provided image.""",  # noqa
            user='[UNUSED_TOKEN_146]user\n',
            assistant='[UNUSED_TOKEN_146]assistant\n',
            eosys='[UNUSED_TOKEN_145]\n',
            eoh='[UNUSED_TOKEN_145]\n',
            eoa='[UNUSED_TOKEN_145]\n',
            separator='\n',
            stop_words=['[UNUSED_TOKEN_145]'],
            **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         user=user,
                         assistant=assistant,
                         eosys=eosys,
                         eoh=eoh,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'internlm' in path and 'xcomposer2' in path:
            if '2d5' in path:
                return 'internlm-xcomposer2d5'
            return 'internlm-xcomposer2'


@MODELS.register_module(name='baichuan2')
class Baichuan2(BaseChatTemplate):
    """Chat template and generation parameters of Baichuan2-7B-Base and
    Baichuan2-7B-Chat models."""

    def __init__(self, user='<reserved_106>', assistant='<reserved_107>', **kwargs):
        super().__init__(user=user, assistant=assistant, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'baichuan2' in path and 'chat' in path:
            return 'baichuan2'


@MODELS.register_module(name='puyu')
class Puyu(BaseChatTemplate):
    """Chat template of puyu model.This is only for internal usage in Shanghai
    AI Laboratory."""

    def __init__(self,
                 meta_instruction='',
                 system='',
                 eosys='',
                 user='',
                 eoh='',
                 assistant='',
                 eoa='',
                 stop_words=None,
                 **kwargs):
        super().__init__(meta_instruction=meta_instruction,
                         system=system,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        if 'puyu' in model_path.lower():
            return 'puyu'


@MODELS.register_module(name='llama2')
class Llama2(BaseChatTemplate):
    """Chat template of LLaMA2 model."""

    def __init__(
            self,
            system='[INST] <<SYS>>\n',
            meta_instruction="""\
You are a helpful, respectful and honest assistant. Always answer as helpfully as possible, while being safe. Your answers should not include any harmful, unethical, racist, sexist, toxic, dangerous, or illegal content. Please ensure that your responses are socially unbiased and positive in nature.

If a question does not make any sense, or is not factually coherent, explain why instead of answering something not correct. If you don't know the answer to a question, please don't share false information.""",  # noqa: E501
            eosys='\n<</SYS>>\n\n',
            assistant=' [/INST] ',
            eoa='</s>',
            separator='<s>[INST] ',
            session_len=4096,
            **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         session_len=session_len,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        if 'llama-2' in model_path.lower() or 'llama2' in model_path.lower():
            return 'llama2'


@MODELS.register_module(name='llama3')
class Llama3(BaseChatTemplate):
    """Chat template of LLaMA3 model."""

    def __init__(self,
                 system='<|start_header_id|>system<|end_header_id|>\n\n',
                 meta_instruction=None,
                 eosys='<|eot_id|>',
                 assistant='<|start_header_id|>assistant<|end_header_id|>\n\n',
                 eoa='<|eot_id|>',
                 user='<|start_header_id|>user<|end_header_id|>\n\n',
                 eoh='<|eot_id|>',
                 stop_words=['<|eot_id|>', '<|end_of_text|>'],
                 **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         assistant=assistant,
                         eoa=eoa,
                         user=user,
                         eoh=eoh,
                         stop_words=stop_words,
                         **kwargs)

    def get_prompt(self, prompt, sequence_start=True):
        if sequence_start:
            return '<|begin_of_text|>' + super().get_prompt(prompt, sequence_start)
        return super().get_prompt(prompt, sequence_start)

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        if sequence_start and not isinstance(messages, str):
            return '<|begin_of_text|>' + super().messages2prompt(messages, sequence_start, **kwargs)
        return super().messages2prompt(messages, sequence_start, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        # reject InternVL2-Llama3-76B
        if 'internvl2' in model_path.lower():
            return None
        if 'llama-3-' in model_path.lower() or 'llama3-' in model_path.lower():
            return 'llama3'


@MODELS.register_module(name=['llama3_1', 'llama3_2'])
class Llama3_1(Llama3):
    """Chat template of LLaMA3.1 model."""

    def __init__(
            self,
            tool="""# Tool Instructions
- Always execute python code in messages that you share.
- When looking for real time information use relevant functions if available else fallback to brave_search



You have access to the following functions:

""",  # noqa
            eotool="""

If a you choose to call a function ONLY reply in the following format:
<{start_tag}={function_name}>{parameters}{end_tag}
where

start_tag => `<function`
parameters => a JSON dict with the function argument name as key and function argument value as value.
end_tag => `</function>`

Here is an example,
<function=example_function_name>{"example_name": "example_value"}</function>

Reminder:
- Function calls MUST follow the specified format
- Required parameters MUST be specified
- Only call one function at a time
- Put the entire function call reply on one line"
- Always add your sources when using search results to answer the user query\n\n""",  # noqa
            knowledge='Cutting Knowledge Date: December 2023\nToday Date: 26 Jul 2024\n\n',
            meta_instruction='You are a helpful assistant.',
            ipython='<|start_header_id|>ipython<|end_header_id|>\n\n',
            eoi='<|eot_id|>',
            stop_words=['<|eot_id|>', '<|end_of_text|>', '<|eom_id|>'],
            **kwargs):
        super().__init__(meta_instruction=meta_instruction, stop_words=stop_words, **kwargs)
        self.ipython = ipython
        self.eoi = eoi
        self.tool = tool
        self.eotool = eotool
        self.knowledge = knowledge

    def messages2prompt(self, messages, sequence_start=True, tools=None, **kwargs):
        """Return the prompt that is concatenated with other elements in the
        chat template.

        Args:
            messages (str | List): user's input prompt
        Returns:
            str: the concatenated prompt
        """
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        box_map = dict(user=self.user,
                       ipython=self.ipython,
                       tool=self.ipython,
                       assistant=self.assistant,
                       system=self.system)
        eox_map = dict(user=self.eoh,
                       ipython=self.eoi,
                       tool=self.eoi,
                       assistant=self.eoa + self.separator,
                       system=self.eosys)
        ret = ''
        tool_prompt = ''
        if tools is not None:
            for tool in tools:
                tool_prompt += "Use the function '{}' to: {}\n{}\n".format(tool['name'], tool['description'],
                                                                           json.dumps(tool, ensure_ascii=False))
        if self.meta_instruction is not None and sequence_start:
            if len(messages) and messages[0]['role'] != 'system':
                if tools is None:
                    ret += f'{self.system}{self.knowledge}{self.meta_instruction}{self.eosys}'
                else:
                    ret += f'{self.system}{self.knowledge}{self.tool}{tool_prompt}{self.eotool}{self.meta_instruction}{self.eosys}'  # noqa
        for message in messages:
            role = message['role']
            content = get_text(message['content'])
            if role == 'assistant' and ('<|python_tag|>' in content or '</function>' in content):
                ret += f'{box_map[role]}{content}<|eom_id|>'
            elif role == 'system' and tools is not None:
                ret += f'{box_map[role]}{self.tool}{tool_prompt}{self.eotool}{content}{eox_map[role]}'
            else:
                ret += f'{box_map[role]}{content}{eox_map[role]}'
        if sequence_start and not isinstance(messages, str):
            ret = '<|begin_of_text|>' + ret
        if len(messages) and messages[-1]['role'] == 'assistant':
            return ret[:-len(eox_map['assistant'])]  # prefix of response
        ret += f'{self.assistant}'
        return ret

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        if 'llama-3.1-' in model_path.lower() or 'llama3.1-' in model_path.lower():
            return 'llama3_1'
        if 'llama-3.2-' in model_path.lower() or 'llama3.2-' in model_path.lower():
            return 'llama3_1'


@MODELS.register_module(name='minicpmv-2d6')
@MODELS.register_module(name='minicpm3')
@MODELS.register_module(name='qwen')
class Qwen7BChat(BaseChatTemplate):
    """Chat template for Qwen-7B-Chat."""

    def __init__(self,
                 system='<|im_start|>system\n',
                 meta_instruction='You are a helpful assistant.',
                 eosys='<|im_end|>\n',
                 user='<|im_start|>user\n',
                 eoh='<|im_end|>\n',
                 assistant='<|im_start|>assistant\n',
                 eoa='<|im_end|>',
                 separator='\n',
                 stop_words=['<|im_end|>'],
                 **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        model_path = model_path.lower()
        if 'qwen' in model_path and not any(keyword in model_path for keyword in ('qwen2.5', 'qwq', 'qwen3')):
            return 'qwen'
        if 'minicpm-v-2_6' in model_path:
            return 'minicpmv-2d6'
        if 'minicpm3-' in model_path:
            return 'minicpm3'


@MODELS.register_module(name='qwen2d5')
class Qwen2d5Chat(Qwen7BChat):
    """Chat template for Qwen2.5-Instruct series."""

    def __init__(
            self,
            system='<|im_start|>system\n',
            meta_instruction='You are Qwen, created by Alibaba Cloud. You are a helpful assistant.',
            eosys='<|im_end|>\n',
            user='<|im_start|>user\n',
            eoh='<|im_end|>\n',
            assistant='<|im_start|>assistant\n',
            eoa='<|im_end|>',
            separator='\n',
            tools="""\n\n# Tools\n\nYou may call one or more functions to assist with the user query.\n\nYou are provided with function signatures within <tools></tools> XML tags:\n<tools>""",  # noqa
            eotools="""\n</tools>\n\nFor each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\n<tool_call>\n{"name": <function-name>, "arguments": <args-json-object>}\n</tool_call>""",  # noqa
            stop_words=['<|im_end|>'],
            **kwargs):

        self.tools = tools
        self.eotools = eotools
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    def messages2prompt(self, messages, sequence_start=True, tools=None, **kwargs):
        """Return the prompt that is concatenated with other elements in the
        chat template.

        Args:
            messages (str | List): user's input prompt
        Returns:
            str: the concatenated prompt
        """
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        box_map = dict(user=self.user, assistant=self.assistant, system=self.system)
        ret = ''
        tool_prompt = ''
        if tools is not None and len(tools) > 0:
            for tool in tools:
                tool_prompt += self.separator
                tool_prompt += f'{{"type": "function", "function": {json.dumps(tool, ensure_ascii=False)}}}'
            if len(messages) and messages[0]['role'] == 'system':
                ret += f"{self.system}{messages[0]['content']}{self.tools}{tool_prompt}{self.eotools}{self.eosys}"
            else:
                ret += f'{self.system}{self.meta_instruction}{self.tools}{tool_prompt}{self.eotools}{self.eosys}'
        else:
            if self.meta_instruction is not None and sequence_start:
                if len(messages) and messages[0]['role'] == 'system':
                    ret += f"{self.system}{messages[0]['content']}{self.eosys}"
                else:
                    ret += f'{self.system}{self.meta_instruction}{self.eosys}'

        for index, message in enumerate(messages):
            if (message['role'] == 'user' or (message['role'] == 'system' and index != 0)
                    or (message['role'] == 'assistant' and message.get('tool_calls') is None)):
                ret += f"{box_map[message['role']]}{get_text(message['content'])}{self.eosys}"
            elif message['role'] == 'assistant':
                ret += '<|im_start|>assistant'
                if message.get('content') is not None:
                    ret += f"{self.separator}{get_text(message['content'])}"

                if message.get('tool_calls') is not None:
                    tool_calls = message['tool_calls']
                    for tool_call in tool_calls:
                        if tool_call.get('function') is not None:
                            tool_call = tool_call['function']
                        if isinstance(tool_call['arguments'], str):
                            tool_call['arguments'] = json.loads(tool_call['arguments'])
                        ret += f'{self.separator}<tool_call>{self.separator}{{"name": "{tool_call["name"]}", "arguments": {json.dumps(tool_call["arguments"], ensure_ascii=False)}}}{self.separator}</tool_call>'  # noqa
                ret += self.eosys
            if message['role'] == 'tool':
                if index == 0 or messages[index - 1]['role'] != 'tool':
                    ret += '<|im_start|>user'
                ret += f"{self.separator}<tool_response>{self.separator}{message['content']}{self.separator}</tool_response>"  # noqa
                if index == len(messages) - 1 or messages[index + 1]['role'] != 'tool':
                    ret += f'{self.eoh}'
        ret += f'{self.assistant}'
        return ret

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        lower_path = model_path.lower()
        if ('qwen2.5' in lower_path or 'qwen2_5' in lower_path) and 'vl' not in lower_path:
            return 'qwen2d5'


@MODELS.register_module(name='qwen2d5-vl')
class Qwen2d5VL(Qwen2d5Chat):

    def __init__(self, meta_instruction='You are a helpful assistant.', **kwargs):
        super().__init__(meta_instruction=meta_instruction, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        lower_path = model_path.lower()
        if ('qwen2.5' in lower_path or 'qwen2_5' in lower_path) and 'vl' in lower_path:
            return 'qwen2d5-vl'


@MODELS.register_module(name='qwq_preview')
class QwQPreview(Qwen2d5Chat):

    def __init__(
            self,
            meta_instruction='You are a helpful and harmless assistant. You are Qwen developed by Alibaba. You should think step-by-step.',  # noqa
            **kwargs):
        super().__init__(meta_instruction=meta_instruction, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        lower_path = model_path.lower()
        if 'qwq' in lower_path and 'preview' in lower_path:
            return 'qwq_preview'


@MODELS.register_module(name='qwq')
class QwQ(Qwen2d5Chat):

    def __init__(self, meta_instruction='', **kwargs):
        super().__init__(meta_instruction=meta_instruction, **kwargs)

    def messages2prompt(self, messages, sequence_start=True, tools=None, **kwargs):
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        return super().messages2prompt(messages, sequence_start, tools, **kwargs) + '<think>\n'

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        lower_path = model_path.lower()
        if 'qwq' in lower_path and 'preview' not in lower_path:
            return 'qwq'


@MODELS.register_module(name='qwen3')
class Qwen3(Qwen2d5Chat):

    def __init__(self, meta_instruction='', **kwargs):
        super().__init__(meta_instruction=meta_instruction, **kwargs)

    def messages2prompt(self, messages, sequence_start=True, tools=None, enable_thinking=None, **kwargs):
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        prompt = super().messages2prompt(messages, sequence_start, tools, **kwargs)

        if enable_thinking is False:
            prompt += '<think>\n\n</think>\n\n'

        return prompt

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        lower_path = model_path.lower()
        if 'qwen3' in lower_path:
            return 'qwen3'


@MODELS.register_module(name='codellama')
class CodeLlama(Llama2):

    def __init__(self, meta_instruction='', suffix_first=False, stop_words=None, **kwargs):
        super().__init__(meta_instruction=meta_instruction, stop_words=stop_words, **kwargs)
        caps = ['completion', 'infilling', 'chat', 'python']
        assert self.capability in caps, \
            f'{self.capability} is not supported. ' \
            f'The supported capabilities are: {caps}'
        self.meta_instruction = meta_instruction
        self.suffix_first = suffix_first
        self.stop_words = stop_words
        if self.capability == 'infilling':
            if self.stop_words is None:
                self.stop_words = ['<EOT>']

    def get_prompt(self, prompt, sequence_start=True):
        if self.capability == 'infilling':
            return self._infill_prompt(prompt)
        elif self.capability == 'chat':
            return super().get_prompt(prompt, sequence_start)
        else:  # python speicalist
            return prompt

    def _infill_prompt(self, prompt):
        prefix, suffix = prompt.split('<FILL>')
        if self.suffix_first:
            # format as "<PRE> <SUF>{suf} <MID> {pre}"
            prompt = f'<PRE> <SUF>{suffix} <MID> {prefix}'
        else:
            # format as "<PRE> {pre} <SUF>{suf} <MID>"
            prompt = f'<PRE> {prefix} <SUF>{suffix} <MID>'
        return prompt

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        if 'codellama' in model_path.lower():
            return 'codellama'


@MODELS.register_module(name='chatglm')
class ChatGLM2(BaseModel):

    def __init__(self, user='问：', eoh='\n\n', assistant='答：', eoa='\n\n', **kwargs):
        super().__init__(**kwargs)
        self._user = user
        self._assistant = assistant
        self._eoh = eoh
        self._eoa = eoa
        self.count = 0

    def get_prompt(self, prompt, sequence_start=True):
        """Get prompt."""
        # need more check
        # https://github.com/THUDM/ChatGLM2-6B/issues/48
        # [64790, 64792] to be prepended
        self.count += 1
        ret = f'[Round {self.count}]\n\n'
        ret += f'{self._user}{prompt}{self._eoh}'
        ret += f'{self._assistant}'
        return ret

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        """Message to prompt."""
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        ret = ''
        count = 0
        for message in messages:
            role = message['role']
            content = get_text(message['content'])
            if role == 'user':
                count += 1
                ret += f'[Round {count}]\n\n'
                ret += f'{self._user}{content}{self._eoh}'
                ret += f'{self._assistant}'
            if role == 'assistant':
                ret += f'{content}'
        return ret

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'chatglm2' in path:
            return 'chatglm'


@MODELS.register_module(name='solar')
class SOLAR(BaseChatTemplate):
    """Chat template of SOLAR model.

    `https://huggingface.co/upstage/SOLAR-0-70b-16bit`
    """

    def __init__(self,
                 system='### System:\n',
                 eosys='\n\n',
                 user='### User:\n',
                 eoh='\n\n',
                 assistant='### Assistant:\n',
                 meta_instruction='',
                 **kwargs):
        super().__init__(**kwargs)
        self.system = system
        self.eosys = eosys
        self.user = user
        self.eoh = eoh
        self.assistant = assistant
        self.meta_instruction = meta_instruction

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        if 'solar' in model_path.lower():
            return 'solar'


@MODELS.register_module(name=['ultracm', 'ultralm'])
class UltraChat(BaseChatTemplate):
    """Template of UltraCM and UltraLM models.

    `https://huggingface.co/openbmb/UltraCM-13b` `https://huggingface.co/openbmb/UltraLM-13b`
    """

    def __init__(
            self,
            system='User: ',
            meta_instruction="""A one-turn chat between a curious user and an artificial intelligence assistant. The assistant gives helpful, very detailed, and polite answers to the user's questions.""",  # noqa: E501
            eosys='</s>\n',
            user='User: ',
            eoh='</s>\n',
            assistant='Assistant: ',
            eoa='</s>',
            separator='\n',
            stop_words=['</s>'],
            **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        if 'ultracm' in model_path.lower():
            return 'ultracm'
        if 'ultralm' in model_path.lower():
            return 'ultralm'


@MODELS.register_module(name=['yi'])
class Yi(BaseChatTemplate):
    """Chat template of Yi model."""

    def __init__(self,
                 system='<|im_start|>system\n',
                 meta_instruction=None,
                 eosys='<|im_end|>\n',
                 user='<|im_start|>user\n',
                 eoh='<|im_end|>\n',
                 assistant='<|im_start|>assistant\n',
                 eoa='<|im_end|>',
                 separator='\n',
                 stop_words=['<|im_end|>', '<|endoftext|>'],
                 **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'yi' in path and 'vl' not in path:
            return 'yi'


@MODELS.register_module(name=['mistral', 'mixtral'])
class MistralChat(BaseChatTemplate):
    """Template of Mistral and Mixtral Instruct models.

    `https://huggingface.co/mistralai/Mistral-7B-Instruct-v0.1`
    `https://huggingface.co/mistralai/Mixtral-8x7B-Instruct-v0.1`
    """

    def __init__(self, user='[INST] ', eoh=' [/INST]', eoa='</s>', **kwargs):
        super().__init__(user=user, eoh=eoh, eoa=eoa, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        model_path = model_path.lower()
        if 'instruct' in model_path or 'llava' in model_path:
            if 'mistral' in model_path:
                return 'mistral'
            if 'mixtral' in model_path:
                return 'mixtral'


@MODELS.register_module(name=['gemma'])
class Gemma(BaseChatTemplate):
    """Template of Gemma models.

    `https://huggingface.co/google/gemma-7b-it`
    """

    def __init__(self,
                 user='<start_of_turn>user\n',
                 eoh='<end_of_turn>\n',
                 assistant='<start_of_turn>model\n',
                 eoa='<end_of_turn>\n',
                 stop_words=['<end_of_turn>'],
                 **kwargs):
        super().__init__(user=user, eoh=eoh, assistant=assistant, eoa=eoa, stop_words=stop_words, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        if 'gemma' in model_path.lower():
            return 'gemma'


@MODELS.register_module(name=['deepseek'])
class Deepseek(BaseChatTemplate):

    def __init__(self,
                 eosys='\n\n',
                 user='User: ',
                 eoh='\n\n',
                 assistant='Assistant: ',
                 eoa='<｜end▁of▁sentence｜>',
                 **kwargs):
        super().__init__(eosys=eosys, user=user, eoh=eoh, assistant=assistant, eoa=eoa, **kwargs)

    def get_prompt(self, prompt, sequence_start=True):
        if self.capability == 'chat':
            return super().get_prompt(prompt, sequence_start)[:-1]
        return super().get_prompt(prompt, sequence_start)

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        return super().messages2prompt(messages, sequence_start, **kwargs)[:-1]

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'deepseek' in path and 'chat' in path and 'vl' not in path:
            return 'deepseek'


@MODELS.register_module(name=['internvl-zh'])
class InternVLZH(BaseChatTemplate):

    def __init__(self, user='<human>: ', eoh=' ', assistant='<bot>: ', eoa='</s>', **kwargs):
        super().__init__(user=user, eoh=eoh, assistant=assistant, eoa=eoa, **kwargs)

    def get_prompt(self, prompt, sequence_start=True):
        if self.capability == 'chat':
            return super().get_prompt(prompt, sequence_start)[:-1]
        return super().get_prompt(prompt, sequence_start)

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        return super().messages2prompt(messages, sequence_start, **kwargs)[:-1]

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'internvl-chat' in path and 'v1-1' in path:
            return 'internvl-zh'


@MODELS.register_module(name=['deepseek-vl'])
class DeepseekVL(BaseChatTemplate):

    def __init__(
            self,
            meta_instruction="""You are a helpful language and vision assistant. You are able to understand the visual content that the user provides, and assist the user with a variety of tasks using natural language.""",  # noqa: E501
            eosys='\n\n',
            user='User: ',
            eoh='\n\n',
            assistant='Assistant: ',
            eoa='<｜end▁of▁sentence｜>',
            **kwargs):
        super().__init__(meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         **kwargs)

    def get_prompt(self, prompt, sequence_start=True):
        if self.capability == 'chat':
            return super().get_prompt(prompt, sequence_start)[:-1]
        return super().get_prompt(prompt, sequence_start)

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        return super().messages2prompt(messages, sequence_start, **kwargs)[:-1]

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'deepseek-vl' in path and 'chat' in path:
            return 'deepseek-vl'


@MODELS.register_module(name=['deepseek-vl2'])
class DeepseekVL2(BaseChatTemplate):

    def __init__(self,
                 meta_instruction='',
                 eosys='',
                 user='<|User|>: ',
                 eoh='\n\n',
                 assistant='<|Assistant|>: ',
                 eoa='<｜end▁of▁sentence｜>',
                 **kwargs):
        super().__init__(meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         **kwargs)

    def get_prompt(self, prompt, sequence_start=True):
        return super().get_prompt(prompt, sequence_start)[:-1]

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        return super().messages2prompt(messages, sequence_start, **kwargs)[:-1]

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'deepseek-vl2' in path:
            return 'deepseek-vl2'


@MODELS.register_module(name='deepseek-coder')
class DeepSeek(BaseChatTemplate):
    """Chat template of deepseek model."""

    def __init__(
            self,
            system='',
            meta_instruction="""You are an AI programming assistant, utilizing the Deepseek Coder model, developed by Deepseek Company, and you only answer questions related to computer science. For politically sensitive questions, security and privacy issues, and other non-computer science questions, you will refuse to answer\n""",  # noqa: E501
            eosys='',
            user='### Instruction:\n',
            eoh='\n',
            assistant='### Response:\n',
            eoa='\n<|EOT|>',
            separator='\n',
            stop_words=['<|EOT|>'],
            **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'deepseek-coder' in path:
            return 'deepseek-coder'


@MODELS.register_module(name=['yi-vl'])
class YiVL(BaseChatTemplate):

    def __init__(
            self,
            meta_instruction="""This is a chat between an inquisitive human and an AI assistant. Assume the role of the AI assistant. Read all the images carefully, and respond to the human's questions with informative, helpful, detailed and polite answers. 这是一个好奇的人类和一个人工智能助手之间的对话。假设你扮演这个AI助手的角色。仔细阅读所有的图像，并对人类的问题做出信息丰富、有帮助、详细的和礼貌的回答。\n\n""",  # noqa: E501
            user='### Human: ',
            eoh='\n',
            assistant='### Assistant:',
            eoa='\n',
            stop_words=['###'],
            **kwargs):
        super().__init__(meta_instruction=meta_instruction,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'yi-vl' in path:
            return 'yi-vl'


@MODELS.register_module(name=['llava-chatml', 'internvl-zh-hermes2'])
class ChatmlDirect(BaseChatTemplate):

    def __init__(self,
                 system='<|im_start|>system\n',
                 meta_instruction='Answer the questions.',
                 eosys='<|im_end|>',
                 user='<|im_start|>user\n',
                 eoh='<|im_end|>',
                 assistant='<|im_start|>assistant\n',
                 eoa='<|im_end|>',
                 separator='',
                 **kwargs):
        super().__init__(system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'llava' in path and 'v1.6-34b' in path:
            return 'llava-chatml'
        if 'internvl-chat' in path and 'v1-2' in path:
            return 'internvl-zh-hermes2'


@MODELS.register_module(name='phi-4')
@MODELS.register_module(name='phi-3')
class Phi3Instruct(BaseChatTemplate):
    """Chat template of InternLM model."""

    def __init__(self,
                 system='<|system|>\n',
                 meta_instruction=None,
                 eosys='<|end|>\n',
                 user='<|user|>\n',
                 eoh='<|end|>\n',
                 assistant='<|assistant|>\n',
                 eoa='<|end|>\n',
                 separator='',
                 stop_words=['<|end|>', '<|endoftext|>', '<|assistant|>'],
                 **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if all([c in path for c in ['phi-3', 'instruct']]):
            return 'phi-3'
        if all([c in path for c in ['phi-4', 'instruct']]):
            return 'phi-4'


@MODELS.register_module(name='internvl2-phi3')
class InternVL2Phi3(Phi3Instruct):

    def __init__(self, meta_instruction='你是由上海人工智能实验室联合商汤科技开发的书生多模态大模型，英文名叫InternVL, 是一个有用无害的人工智能助手。', **kwargs):
        super().__init__(meta_instruction=meta_instruction, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'internvl2-4b' in path:
            return 'internvl2-phi3'


@MODELS.register_module(name='chatglm3')
class ChatGLM3(BaseChatTemplate):
    """Chat template of chatglm3 model."""

    def __init__(self,
                 system='<|system|>\n ',
                 meta_instruction=None,
                 eosys='',
                 user='<|user|>\n ',
                 eoh='',
                 assistant='<|assistant|>\n ',
                 eoa='',
                 separator='',
                 stop_words=['<eos>'],
                 **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)
        self.start = '[gMASK]sop'

    def get_prompt(self, prompt, sequence_start=True):
        """Return the prompt that is concatenated with other elements in the
        chat template.

        Args:
            prompt (str): user's input prompt
            sequence_start (bool): indicator for the first round chat of a
               session sequence
        Returns:
            str: the concatenated prompt
        """
        prompt = super().get_prompt(prompt, sequence_start)
        if sequence_start:
            prompt = self.start + prompt
        return prompt

    def messages2prompt(self, messages, sequence_start=True, **kwargs):
        """Return the prompt that is concatenated with other elements in the
        chat template.

        Args:
            messages (str | List): user's input prompt
        Returns:
            str: the concatenated prompt
        """
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        return self.start + super().messages2prompt(messages, sequence_start, **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'chatglm3' in path:
            return 'chatglm3'


@MODELS.register_module(name='glm4')
class Glm4Chat(ChatGLM3):
    """Chat template of glm-4 model."""

    def __init__(self,
                 system='<|system|>\n',
                 user='<|user|>\n',
                 assistant='<|assistant|>\n',
                 stop_words=['<|user|>', '<|endoftext|>', '<|observation|>'],
                 **kwargs):
        super().__init__(system=system, user=user, assistant=assistant, stop_words=stop_words, **kwargs)
        self.start = '[gMASK]<sop>'

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'glm-4' in path:
            return 'glm4'


@MODELS.register_module(name='codegeex4')
class CodeGeeX4Chat(BaseChatTemplate):
    """Chat template of THUDM/codegeex4-all-9b model."""

    def __init__(self,
                 system='<|system|>\n',
                 meta_instruction='你是一位智能编程助手，你叫CodeGeeX。你会为用户回答关于编程、代码、计算机方面的任何问题，并提供格式规范、可以执行、准确安全的代码，并在必要时提供详细的解释。',
                 eosys='',
                 user='<|user|>\n',
                 eoh='',
                 assistant='<|assistant|>\n',
                 eoa='',
                 separator='',
                 stop_words=['<|endoftext|>', '<|user|>', '<|observation|>'],
                 **kwargs):
        super().__init__(system=system,
                         meta_instruction=meta_instruction,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'codegeex4' in path:
            return 'codegeex4'


@MODELS.register_module(name='internvl-phi3')
class InternVLPhi3(Phi3Instruct):
    """Chat template of InternVL Chat 4B model."""

    def __init__(self,
                 meta_instruction='You are an AI assistant whose name is Phi-3.',
                 eosys='<|end|>',
                 eoh='<|end|>',
                 eoa='<|end|>',
                 separator='',
                 **kwargs):
        super().__init__(meta_instruction=meta_instruction,
                         eosys=eosys,
                         eoh=eoh,
                         eoa=eoa,
                         separator=separator,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if all([c in path for c in ['mini-internvl-chat', '4b', 'v1-5']]):
            return 'internvl-phi3'


@MODELS.register_module(name='molmo')
class Molmo(BaseChatTemplate):

    def __init__(self,
                 user=' User: ',
                 eoh='',
                 assistant=' Assistant:',
                 eoa='',
                 separator=' ',
                 stop_words=['<|endoftext|>'],
                 **kwargs):
        super().__init__(user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'molmo' in path:
            return 'molmo'


@MODELS.register_module(name='llama4')
class Llama4(BaseChatTemplate):

    def __init__(self,
                 system='<|header_start|>system<|header_end|>\n\n',
                 user='<|header_start|>user<|header_end|>\n\n',
                 assistant='<|header_start|>assistant<|header_end|>\n\n',
                 eosys='<|eot|>',
                 eoh='<|eot|>',
                 eoa='<|eot|>',
                 separator='',
                 stop_words=['<|end_of_text|>', '<|eom|>', '<|eot|>'],
                 **kwargs):
        super().__init__(system=system,
                         eosys=eosys,
                         user=user,
                         eoh=eoh,
                         assistant=assistant,
                         eoa=eoa,
                         separator=separator,
                         stop_words=stop_words,
                         **kwargs)

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'llama-4' in path:
            return 'llama4'


@MODELS.register_module(name='intern-s1')
@MODELS.register_module(name='interns1')
class InternS1(InternVL2_5):

    def __init__(
            self,
            tool='\n\nYour response should consist of a reasoning step (**thought**) followed immediately by a function call in valid JSON format. Wrap each function call using the `<|action_start|><|plugin|>` and `<|action_end|>` tags.\n\n**Format example:**\n\n```\n(Your thought goes here...)\n\n<|action_start|><|plugin|>\n{\n    "name": "tool_name",\n    "parameters": {\n        "parameter1": "value1",\n        "parameter2": "value2"\n    }\n}\n<|action_end|>\n```\n\n# External Tools\nYou have access to these tools:\n',  # noqa: E501
            eotool='',
            meta_instruction='You are an expert reasoner with extensive experience in all areas. You approach problems through systematic thinking and rigorous reasoning. Your response should reflect deep understanding and precise logical thinking, making your solution path and reasoning clear to others. Please put your thinking process within <think>...</think> tags.',  # noqa: E501
            **kwargs):
        super(InternVL2_5, self).__init__(meta_instruction=meta_instruction, **kwargs)

        self.tool = tool or ''
        self.eotool = eotool or ''

    def messages2prompt(self, messages, sequence_start=True, tools=None, enable_thinking=None, **kwargs):
        """Return the prompt that is concatenated with other elements in the
        chat template.

        Args:
            messages (str | List): user's input prompt
        Returns:
            str: the concatenated prompt
        """
        if isinstance(messages, str):
            return self.get_prompt(messages, sequence_start)
        box_map = dict(user=self.user,
                       assistant=self.assistant,
                       system=self.system,
                       environment=self.environment,
                       tool=self.environment)
        eox_map = dict(user=self.eoh,
                       assistant=self.eoa + self.separator,
                       system=self.eosys,
                       environment=self.eoenv,
                       tool=self.eoenv)
        name_map = dict(plugin=self.plugin, interpreter=self.interpreter)

        ret = ''

        if tools:
            tools_prompt = dict(
                role='system',
                name='plugin',  # only support internlm2
                content=f'{self.tool}{json.dumps(tools, ensure_ascii=False, indent=2)}{self.eotool}')

            if messages[0]['role'] == 'system':
                tools_prompt['content'] = messages[0]['content'] + tools_prompt['content']
                messages[0] = tools_prompt
            else:
                if self.meta_instruction is not None and sequence_start and enable_thinking is not False:
                    tools_prompt['content'] = self.meta_instruction + tools_prompt['content']
                else:
                    tools_prompt['content'] = tools_prompt['content'].lstrip('\n')
                messages.insert(0, tools_prompt)
        elif self.meta_instruction is not None and sequence_start:
            if len(messages):
                if messages[0]['role'] != 'system' and enable_thinking is not False:
                    ret += f'{self.system}{self.meta_instruction}{eox_map["system"]}'
        # find index of last user input section
        last_user_idx = -1
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx]['role'] == 'user':
                last_user_idx = idx
                break

        for idx, message in enumerate(messages):
            role = message['role']
            content = get_text(message['content'])
            if last_user_idx != -1 and idx > last_user_idx and message.get('reasoning_content', None) is not None:
                content = f'<think>\n{message["reasoning_content"]}\n</think>\n{content}'
            if role == 'assistant' and message.get('tool_calls', None) is not None:
                for tool_call in message['tool_calls']:
                    function = tool_call.get('function', {})
                    function['name'] = function.get('name', '')
                    function['parameters'] = function.get('parameters', function.get('arguments', ''))
                    function.pop('arguments')
                    if isinstance(function['parameters'], str):
                        function['parameters'] = json.loads(function['parameters'])
                    content += f'<|action_start|><|plugin|>\n{json.dumps(function, ensure_ascii=False)}\n<|action_end|>'

            if 'name' in message:
                begin = box_map[role].strip()
                if message['name'] in name_map:
                    begin = begin + f" name={name_map[message['name']]}\n"
                elif role == 'tool':
                    begin = begin + f" name={name_map['plugin']}\n"
            else:
                begin = box_map[role]
            ret += f'{begin}{content}{eox_map[role]}'
        if len(messages) and messages[-1]['role'] == 'assistant':
            return ret[:-len(eox_map['assistant'])]  # prefix of response
        ret += f'{self.assistant}'

        if enable_thinking is not False:
            ret += '<think>'
        return ret

    @classmethod
    def match(cls, model_path: str) -> Optional[str]:
        """Return the model_name that was registered to MODELS.

        Args:
            model_path (str): the model path used for matching.
        """
        path = model_path.lower()
        if 'intern-s1' in path or 'interns1' in path:
            return 'intern-s1'


def best_match_model(query: str) -> Optional[str]:
    """Get the model that matches the query.

    Args:
        query (str): the input query. Could be a model path.

    Return:
        str: the possible model name.
    """
    for name, model in MODELS.module_dict.items():
        matched_name = model.match(query)  # cache the result to avoid matching twice
        if matched_name:
            return matched_name
    logger.warning(f'Did not find a chat template matching {query}.')
    return 'base'
