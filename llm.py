from openai import OpenAI
from langsmith.wrappers import wrap_openai

from config.config import Settings

class LLMFactory:
    def __init__(self):

        settings = Settings()
        self.llm_client = OpenAI(
                api_key = settings.llm.api_key,
                base_url= settings.llm.base_url
            )
    
    def _get_structured_response(
            self, 
            human_prompt: str, 
            parser, 
            model_id: str = "gemini-2.5-flash", 
            sys_prompt: str = None
        ):
        
        """
            Gets a structured response from a language model using the provided parameters.
            Args:
                model_id (str): The identifier for the language model to use.
                sys_prompt (str, optional): System prompt to provide context to the model. If None, only the user message is sent.
                human_prompt (str): The user's message or prompt to send to the model.
                parser (dict): The response format parser configuration.
            Returns:
                The parsed structured response from the model.
            Note:
                This method uses the beta API endpoint for parsing chat completions.
        """        
        if sys_prompt:
            messages = [
                {'role':'system', 'content':sys_prompt},
                {'role':'user', 'content': human_prompt}
            ]
        else:
            messages = [
                {'role':'user', 'content': human_prompt}
            ]

        try:
            response = self.llm_client.beta.chat.completions.parse(
                model = model_id,
                messages = messages,
                response_format = parser
            )

            return response.choices[0].message.parsed
        
        except Exception as e:
            print(f"[ERROR in LLM class]: {e}")
            return None
        
    def _get_normal_response(
            self, 
            human_prompt: str, 
            model_id: str = "gemini-2.5-flash", 
            sys_prompt: str = ""
        ):

        """
            Gets a structured response from a language model using the provided parameters.
            Args:
                model_id (str): The identifier for the language model to use.
                sys_prompt (str, optional): System prompt to provide context to the model. If None, only the user message is sent.
                human_prompt (str): The user's message or prompt to send to the model.
            Returns:
                The parsed structured response from the model.
        """        
        if sys_prompt:
            messages = [
                {'role':'system', 'content':sys_prompt},
                {'role':'user', 'content': human_prompt}
            ]
        else:
            messages = [
                {'role':'user', 'content': human_prompt}
            ]

        try:
            response = self.llm_client.chat.completions.create(
                model = model_id,
                messages = messages,
            )

            return response.choices[0].message.content
        
        except Exception as e:
            print(f"[ERROR in LLM class]: {e}")
            return None