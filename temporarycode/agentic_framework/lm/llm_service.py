# lm/llm_service.py
import openai
import asyncio
import yaml
import json
from utils.logger import logger
import os
import json
import logging
import subprocess
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field
from panacea_ai_framework.utilities.exceptions.context_window_exceeding_exception import (
    LLMContextLengthExceededException,
)
import litellm
from litellm import get_supported_openai_params

from panacea_ai_framework.utilities import Converter

import warnings
import sys
from contextlib import contextmanager
import io

class FilteredStream(io.StringIO):
    def write(self, s):
        if (
            "Give Feedback / Get Help: https://github.com/BerriAI/litellm/issues/new"
            in s
            or "LiteLLM.Info: If you need to debug this error, use `litellm.set_verbose=True`"
            in s
        ):
            return
        super().write(s)

@contextmanager
def suppress_warnings():
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore")

        # Redirect stdout and stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = FilteredStream()
        sys.stderr = FilteredStream()

        try:
            yield
        finally:
            # Restore stdout and stderr
            sys.stdout = old_stdout
            sys.stderr = old_stderr

LLM_CONTEXT_WINDOW_SIZES = {
    # openai
    "gpt-4": 8192,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4-turbo": 128000,
    "o1-preview": 128000,
    "o1-mini": 128000,
    # deepseek
    "deepseek-chat": 128000,
    # groq
    "gemma2-9b-it": 8192,
    "gemma-7b-it": 8192,
    "llama3-groq-70b-8192-tool-use-preview": 8192,
    "llama3-groq-8b-8192-tool-use-preview": 8192,
    "llama-3.1-70b-versatile": 131072,
    "llama-3.1-8b-instant": 131072,
    "llama-3.2-1b-preview": 8192,
    "llama-3.2-3b-preview": 8192,
    "llama-3.2-11b-text-preview": 8192,
    "llama-3.2-90b-text-preview": 8192,
    "llama3-70b-8192": 8192,
    "llama3-8b-8192": 8192,
    "mixtral-8x7b-32768": 32768,
}

class LLM:
    def __init__(
        self,
        model: str,
        timeout: Optional[Union[float, int]] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        n: Optional[int] = None,
        stop: Optional[Union[str, List[str]]] = None,
        max_completion_tokens: Optional[int] = None,
        max_tokens: Optional[int] = None,
        presence_penalty: Optional[float] = None,
        frequency_penalty: Optional[float] = None,
        logit_bias: Optional[Dict[int, float]] = None,
        response_format: Optional[Dict[str, Any]] = None,
        seed: Optional[int] = None,
        logprobs: Optional[bool] = None,
        top_logprobs: Optional[int] = None,
        base_url: Optional[str] = None,
        api_version: Optional[str] = None,
        api_key: Optional[str] = None,
        callbacks: List[Any] = [],
        config_path='config/config.yaml'
        **kwargs,
    ):
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.top_p = top_p
        self.n = n
        self.stop = stop
        self.max_completion_tokens = max_completion_tokens
        self.max_tokens = max_tokens
        self.presence_penalty = presence_penalty
        self.frequency_penalty = frequency_penalty
        self.logit_bias = logit_bias
        self.response_format = response_format
        self.seed = seed
        self.logprobs = logprobs
        self.top_logprobs = top_logprobs
        self.base_url = base_url
        self.api_version = api_version
        self.api_key = api_key
        self.callbacks = callbacks
        self.kwargs = kwargs
        self.config = self.load_config(config_path)
        self.api_key = self.config['api_keys']['openai']
        openai.api_key = self.api_key

        litellm.drop_params = True
        litellm.set_verbose = False
        litellm.callbacks = callbacks

     def load_config(self, config_path):
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)

    async def generate_task_plan(self, query):
        try:
            prompt = f"""
            You are an intelligent orchestrator for a multi-agent AI system. Given a user query, generate a JSON task plan with the following structure:
            {{
                "tasks": [
                    {{
                        "agent_type": "AgentType",
                        "parameters": {{"param1": "value1", "param2": "value2"}}
                    }}
                ],
                "synthesis_instructions": "Instructions for synthesizing the response."
            }}
            The task plan should include all necessary agents to fulfill the query.

            Query: {query}

            Task Plan:
            """
            response = await openai.Completion.acreate(
                engine="gpt-4",
                prompt=prompt,
                max_tokens=500,
                n=1,
                stop=None,
                temperature=0.5,
            )
            task_plan_text = response.choices[0].text.strip()
            # Try to parse JSON
            try:
                task_plan = json.loads(task_plan_text)
                return task_plan
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse task plan JSON: {e}")
                return {"tasks": [], "synthesis_instructions": ""}
        except Exception as e:
            logger.error(f"LLM Service Error: {e}")
            return {"tasks": [], "synthesis_instructions": ""}


    def call(self, messages: List[Dict[str, str]], callbacks: List[Any] = []) -> str:
        with suppress_warnings():
            if callbacks and len(callbacks) > 0:
                litellm.callbacks = callbacks

            try:
                params = {
                    "model": self.model,
                    "messages": messages,
                    "timeout": self.timeout,
                    "temperature": self.temperature,
                    "top_p": self.top_p,
                    "n": self.n,
                    "stop": self.stop,
                    "max_tokens": self.max_tokens or self.max_completion_tokens,
                    "presence_penalty": self.presence_penalty,
                    "frequency_penalty": self.frequency_penalty,
                    "logit_bias": self.logit_bias,
                    "response_format": self.response_format,
                    "seed": self.seed,
                    "logprobs": self.logprobs,
                    "top_logprobs": self.top_logprobs,
                    "api_base": self.base_url,
                    "api_version": self.api_version,
                    "api_key": self.api_key,
                    "stream": False,
                    **self.kwargs,
                }

                # Remove None values to avoid passing unnecessary parameters
                params = {k: v for k, v in params.items() if v is not None}

                response = litellm.completion(**params)
                return response["choices"][0]["message"]["content"]
            except Exception as e:
                if not LLMContextLengthExceededException(
                    str(e)
                )._is_context_limit_error(str(e)):
                    logging.error(f"LiteLLM call failed: {str(e)}")

                raise  # Re-raise the exception after logging

    def supports_function_calling(self) -> bool:
        try:
            params = get_supported_openai_params(model=self.model)
            return "response_format" in params
        except Exception as e:
            logging.error(f"Failed to get supported params: {str(e)}")
            return False

    def supports_stop_words(self) -> bool:
        try:
            params = get_supported_openai_params(model=self.model)
            return "stop" in params
        except Exception as e:
            logging.error(f"Failed to get supported params: {str(e)}")
            return False

    def get_context_window_size(self) -> int:
        # Only using 75% of the context window size to avoid cutting the message in the middle
        return int(LLM_CONTEXT_WINDOW_SIZES.get(self.model, 8192) * 0.75)
