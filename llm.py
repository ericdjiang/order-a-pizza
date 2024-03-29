from dataclasses import dataclass
import os
from dotenv import load_dotenv
import google.generativeai as genai
from termcolor import colored
from openai import OpenAI

load_dotenv()

SOLAR_API_KEY = os.getenv("SOLAR_API_KEY")
GEMINI_PRO_API_KEY = os.getenv("GEMINI_PRO_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

genai.configure(api_key=GEMINI_PRO_API_KEY)


@dataclass
class GeminiUsage:
    input_char_count: int = 0
    output_char_count: int = 0

    def increment(self, prompt: str, llm_output: str):
        self.input_char_count += len(prompt)
        self.output_char_count += len(llm_output)

        turn_cost = self._calculate_cost(len(prompt), len(llm_output))

        print(colored(f"Turn cost: ${turn_cost}", "green"))
        print(colored(f"Total cost: ${self.total_cost}", "blue"))

        return turn_cost

    @property
    def total_cost(self):
        return self._calculate_cost(self.input_char_count, self.output_char_count)

    def _calculate_cost(self, input_char_count, output_char_count):
        input_cost_per_1k_chars: float = 0.00025
        output_cost_per_1k_chars: float = 0.0005

        return (
            input_char_count * input_cost_per_1k_chars / 1000
            + output_char_count * output_cost_per_1k_chars / 1000
        )


def call_gemini(
    prompt: str,
    gemini_usage: GeminiUsage = GeminiUsage(),
    temperature=0.3,
    chat: bool = True,
) -> str:
    model = genai.GenerativeModel(
        model_name="gemini-pro",
        generation_config={
            "temperature": temperature,
            "top_p": 1,
            "top_k": 1,
            "max_output_tokens": 2048,
        },
    )

    if chat:
        convo = model.start_chat(history=[])
        convo.send_message(prompt)
        llm_output = convo.last.text
    else:
        response = model.generate_content(prompt)
        llm_output = response.text
        raise Exception("Can't use non chat")

    gemini_usage.increment(prompt=prompt, llm_output=llm_output)

    return llm_output


def call_openai(prompt: str, temperature: float = 0.0):
    client = OpenAI(
        api_key=OPENAI_API_KEY,
    )

    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant who is able to interact with a web browser.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
    )

    return response.choices[0].message.content


def call_solar(prompt: str, temperature: float = 0.0):
    client = OpenAI(api_key=SOLAR_API_KEY, base_url="https://api.upstage.ai/v1/solar")

    response = client.chat.completions.create(
        model="solar-1-mini-chat",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful assistant who is able to interact with a web browser.",
            },
            {"role": "user", "content": prompt},
        ],
        temperature=temperature,
    )

    return response.choices[0].message.content
