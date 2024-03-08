from __future__ import annotations
import re
from typing import List, Callable, Optional, Dict, Any, Tuple
from bs4 import BeautifulSoup
from dataclasses import dataclass
from pydantic import BaseModel, Field
import textwrap
from playwright.sync_api import Page, sync_playwright
import ast
from webpage import html_diff, simplify_html, sanitize_html_for_diffing
from llm import GeminiUsage, call_gemini
import minify_html
from termcolor import colored, cprint
import inspect
import time
from enum import Enum


@dataclass
class Action:
    description: str
    fn: Callable
    args: BaseModel


def go_to_url(url: str, page, id_to_xpath=None):
    page.goto(url if "://" in url else f"https://{url}")
    return ""


class GoToUrlArgs(BaseModel):
    url: str = Field(description="The URL of the webpage to open")


class GoToUrlAction(Action):
    description = "Open a webpage by URL"
    fn = go_to_url
    args = GoToUrlArgs


def click_html_element(id: str, page, id_to_xpath):
    page.locator(f"xpath={id_to_xpath[id]}").click()
    return ""


class ClickElementByIdArgs(BaseModel):
    id: str = Field(description="The id of the <a> or <button> to click.")


class ClickElementByIdAction(Action):
    description = "Click an HTML <a> tag or <button> identified by its ID"
    fn = click_html_element
    args = ClickElementByIdArgs


def fill_text_in_input(id: str, text: str, page, id_to_xpath):
    page.locator(f"xpath={id_to_xpath[id]}").fill(text)
    return ""


class FillTextByIdArgs(BaseModel):
    id: str = Field(description="The ID of the input or text area to fill with text")
    text: str = Field(description="The text to type in the input")


class FillTextByIdAction(Action):
    description = "Type text into an input or textarea identified by its ID. Important: This function can ONLY be called with an ID that belongs directly to an <input> or <textarea> tag."
    fn = fill_text_in_input
    args = FillTextByIdArgs


def choose_dropdown_values(id: str, values: List[str], page, id_to_xpath):
    page.locator(f"xpath={id_to_xpath[id]}").select_option(value=values)
    return ""


class SelectOptionsByIdAction(Action):
    description = "Select value(s) for a <select> tag identified by its ID. The `values` list must contain at least one string option to select. Important: This function can ONLY be called with an ID that belongs directly to a <select> tag."
    fn = choose_dropdown_values
    args = BaseModel


class TypeTextArgs(BaseModel):
    text: str = Field(description="The text to type")


class TypeTextAction(Action):
    description = "Type text"
    fn = fill_text_in_input
    args = FillTextByIdArgs


@dataclass
class ActionToExecute:
    action_name: str
    args: str

    def __str__(self):
        return f"{self.action_name}({self.args})"


@dataclass
class TurnException:
    python_code: str
    exception: Exception


@dataclass
class Turn:
    prompt: str
    available_actions: List[Action]
    llm_output: str
    observations: str
    reasoning: str
    action_description: str
    actions_to_execute: List[ActionToExecute]
    browser_page: BrowserPage
    status: TurnStatus
    exception: Optional[TurnException] = None
    html_diff: Optional[str] = None

    def execute_actions(self):
        for action_to_execute in self.actions_to_execute:
            action: Action = next(
                (
                    action
                    for action in self.available_actions
                    if action.fn.__name__ == action_to_execute.action_name
                ),
                None,
            )
            if action is not None:
                # Initialize empty lists and dictionaries for args and kwargs
                args = []
                kwargs = {}

                # Split the string by commas to handle args and kwargs separately
                # This time, we need to account for potential commas within the kwarg values
                parts = []
                buffer = ""
                inside_quotes = False
                for char in action_to_execute.args:
                    if char in ("'", '"'):
                        inside_quotes = not inside_quotes
                    elif char == "," and not inside_quotes:
                        parts.append(buffer.strip())
                        buffer = ""
                        continue
                    buffer += char
                parts.append(buffer.strip())  # Add the last buffered part

                # Process each part to separate args and kwargs
                for part in parts:
                    if "=" in part and not inside_quotes:
                        # This is a kwarg, find the first '=' that separates the key and value
                        split_index = part.index("=")
                        key = part[:split_index].strip()
                        value = part[split_index + 1 :].strip()
                        # Use ast.literal_eval to safely evaluate the value
                        kwargs[key] = ast.literal_eval(value)
                    else:
                        # This is an arg, use ast.literal_eval for safe evaluation
                        args.append(ast.literal_eval(part))

                cprint(
                    f"Executing {action.fn.__name__}({action_to_execute.args})",
                    "magenta",
                )

                try:
                    action.fn(
                        *args,
                        **kwargs,
                        **{
                            "page": self.browser_page.page,
                            "id_to_xpath": self.browser_page.id_to_xpath,
                        },
                    )

                    if any(
                        action.description == action_that_requires_wait.description
                        for action_that_requires_wait in [
                            ClickElementByIdAction,
                            GoToUrlAction,
                        ]
                    ):
                        time.sleep(5)
                    else:
                        cprint("NOT WAITING", "red")
                        cprint(action, "red")
                    self._handle_successful_execution()
                except Exception as e:
                    print(colored(e, "red"))
                    self.status = TurnStatus.FAILED
                    self.exception = TurnException(
                        python_code=str(action_to_execute),
                        exception=e,
                    )
                    raise e

            else:
                self.status = TurnStatus.FAILED
                e = Exception("LLM specified an action that does not exist")
                self.exception = TurnException(
                    python_code=str(action_to_execute),
                    exception=e,
                )
                raise e

    def stringify_actions_to_execute(self):
        return "\n".join(str(action) for action in self.actions_to_execute)

    def _handle_successful_execution(self):

        print(f"The current browser url is {self.browser_page.page.url}")
        print(f"The previous browser url was {self.browser_page.url}")

        if self.browser_page.page.url != self.browser_page.url:
            cprint("NAVIGATED TO NEW PAGE")
            self.status = TurnStatus.NAVIGATED_TO_NEW_PAGE

            try:
                new_html = self.browser_page.page.content()
                old_html = self.browser_page.html

                if old_html:
                    sanit_1 = sanitize_html_for_diffing(old_html).prettify()
                    sanit_2 = sanitize_html_for_diffing(new_html).prettify()
                    self.html_diff = html_diff(sanit_1, sanit_2)

            except Exception as e:
                cprint("Error calculating diff", e)
                pass

        else:
            self.status = TurnStatus.MODIFIED_PAGE

    @classmethod
    def construct(
        cls: Turn,
        prompt: str,
        available_actions: List[Action],
        llm_output: str,
        browser_page: BrowserPage,
    ):
        turn = cls(
            prompt=prompt,
            available_actions=available_actions,
            llm_output=llm_output,
            observations=cls.extract_observations(llm_output),
            reasoning=cls.extract_reasoning(llm_output),
            action_description=cls.extract_action_description(llm_output),
            actions_to_execute=cls.extract_actions_to_execute(llm_output),
            browser_page=browser_page,
            status=TurnStatus.PENDING,
        )

        return turn

    @staticmethod
    def extract_observations(llm_output: str):
        pattern = r"Observations([\s\S]*)Reasoning"
        match = re.search(pattern, llm_output)
        if match:
            return match.group(1).strip()

        raise Exception("Could not find Observations")

    @staticmethod
    def extract_reasoning(llm_output: str):
        pattern = r"Reasoning([\s\S]*)Action"
        match = re.search(pattern, llm_output)
        if match:
            return match.group(1).strip()

        raise Exception("Could not find Reasoning")

    @staticmethod
    def extract_actions_to_execute(llm_output: str) -> List[ActionToExecute]:
        pattern = r"\S+\(.*\)"
        action_strings = re.findall(pattern, llm_output)

        actions_to_execute = []
        for action_string in action_strings:
            match = re.search(r"(\w+)\((.*)\)", action_string)
            action_name, args_str = match.groups()
            actions_to_execute.append(
                ActionToExecute(action_name=action_name, args=args_str)
            )

        return actions_to_execute

    @staticmethod
    def extract_action_description(llm_output: str) -> str:
        pattern = r"Action \*\*([\s\S]*)`"
        match = re.search(pattern, llm_output)
        if match:
            return match.group(1).strip().replace("`", "")

        return Turn.extract_reasoning(llm_output)  # TODO: Fix

        raise Exception("Could not find Action Description")

    def stringify(self):
        if self.status == TurnStatus.FAILED:
            raise Exception("Cannot stringify failed turn")
        return f"On {self.browser_page.url}, you decided: {self.reasoning}"


class TurnStatus(Enum):
    PENDING = "pending"
    FAILED = "failed"
    MODIFIED_PAGE = "successfully modified page"
    NAVIGATED_TO_NEW_PAGE = "successfully navigated to new page"


@dataclass
class TurnHistory:
    turns: List[Turn]

    def save_turn(self, turn: Turn):
        self.turns.append(turn)

    @property
    def current_page_actions(self) -> Optional[Tuple[str, str]]:
        successful_turns = [
            turn for turn in self.turns if turn.status != TurnStatus.FAILED
        ]
        current_page_actions: List[str] = []
        current_page_action_descriptions: List[str] = []
        i = len(successful_turns) - 1
        while i >= 0 and successful_turns[i].status == TurnStatus.MODIFIED_PAGE:
            code_block = successful_turns[i].stringify_actions_to_execute()
            current_page_actions.append(code_block)
            current_page_action_descriptions.append(
                successful_turns[i].action_description
            )
            i -= 1

        actions_str = f"\n".join(
            current_page_actions
        )  # May need to consider numbering each code block in the future
        action_descriptions_str = "\n".join(current_page_action_descriptions)

        return (actions_str, action_descriptions_str) if actions_str else None

    def summarize_actions(self) -> Optional[str]:
        successful_turns = [
            turn for turn in self.turns if turn.status != TurnStatus.FAILED
        ]
        turn_history = "\n".join(
            f"{i + 1}. {turn.action_description}"
            for i, turn in enumerate(successful_turns)
        )

        if not turn_history:
            return None

        prompt = f"In a paragraph, concisely summarize the following actions taken by the user on a web browser. Address the user as 'you'. In your last sentence, you must describe the outcome of the action.\n{turn_history}"

        if (
            self.turns
            and self.turns[-1].status != TurnStatus.FAILED
            and self.turns[-1].html_diff
            and len(self.turns[-1].html_diff) < 19000
        ):
            prompt = f"In a paragraph, concisely summarize the following actions taken by the user on a web browser. Address the user as 'you'. The user performed the following actions:\n{turn_history}\n\n Important: in your last sentence, you must describe the outcome of the most recent action based on webpage diff:\n{self.turns[-1].html_diff}"

        cprint(prompt, "yellow")

        time.sleep(1)
        return call_gemini(
            prompt=prompt,
            gemini_usage=gemini_usage,
        )


@dataclass
class BrowserPage:
    page: Page
    simplified_html: Optional[str]
    id_to_xpath: Optional[Dict[str, str]]
    html: Optional[str]
    url: Optional[str]

    @classmethod
    def construct(cls: BrowserPage, page: Page) -> BrowserPage:
        if page.url == "about:blank":
            return cls(
                page=page, simplified_html=None, id_to_xpath=None, html=None, url=None
            )

        soup, id_to_xpath = simplify_html(page.content(), collapse_tags=True)

        return cls(
            page=page,
            simplified_html=minify_html.minify(str(soup)),
            id_to_xpath=id_to_xpath,
            html=page.content(),
            url=page.url,
        )


def format_action_for_prompt(action: Action):
    # schema = action.args.model_json_schema()["properties"]
    # for v in schema.values():
    #     del v["title"]

    signature = inspect.signature(action.fn)
    params = [
        param
        for param in signature.parameters.values()
        if param.name not in ["page", "id_to_xpath"]
    ]
    param_str = ", ".join(str(param) for param in params)

    return f"{action.fn.__name__}({param_str}): {action.description}"


def fmt_browser_agent_prompt(
    task: str,
    available_actions: List[Action],
    turn_history: TurnHistory,
    browser_page: BrowserPage,
):

    formatted_actions = "\n".join(
        format_action_for_prompt(action) for action in available_actions
    )
    prompt = [
        (
            f"You are a helpful assistant who is interacting with a browser on behalf of the user. Your purpose is to help a user complete the following task:\n{task}\n\nYou are a skilled web surfer who is able to perform the following actions to interact with the browser:\n{formatted_actions}"
        )
    ]

    summarized_actions = turn_history.summarize_actions()

    if turn_history.turns and turn_history.turns[-1].status == TurnStatus.FAILED:
        failed_turn = turn_history.turns[-1]
        prompt.append(
            f"Important: In the previous turn, you tried to perform the following action and it failed:\n{failed_turn.exception.python_code}\nThe exception was: {failed_turn.exception.exception}\nImportant: This action didn't work, so DO NOT perform it again."
        )

    prompt.append(
        f"""\
        You must carefully read over the current webpage's HTML, and based on the current state of the webpage and the progress that has already been made, decide the single most logical next action to take to help advance in achieving the task: {task}. Previously, you have already performed the following actions: {summarized_actions}
        
        Your response must be in the following format with sections named Observations, Reasoning, and Action:
        ```
        ** Observations ** 
        
        Carefully read the HTML of the current webpage. Based on the HTML, explain the purpose of the webpage and identify the important HTML elements.

        ** Reasoning **
        
        Think critically about what action you can perform on the HTML to help advance in the user task. In your reasoning process, it is critical to take into account BOTH the HTML contents and the progress you have already made in completing the task. You MUST explain why the action you choose makes sense given the previous actions that have already been performed. If the current webpage will not help you advance in the task, feel free to go to a different URL. Important: You may only select a single action to take, and you must not call multiple actions. 

        ** Action **

        Describe the action you will perform to the user. Then, in a new line, call the action in the following format: action_name(param_name="argument")
        ```"""
    )

    """
    For example, a real response for a different task to book a Delta plane ticket is below:
    '''
    Observations: I am currently on a Delta website that allows the user to search for flights that match specific filters. The webpage has multiple input filters, including a from and to input filter and a date range picker. I have verified that all other relevant input filters for flight details have been filled in, and the only remaining required filter is the destination airport. I must set this destination airport to be "SFO" before I can click the search button.

    Action: fill_text_by_id(id='21', text='SFO')
    '''
    """

    # if turn_history.current_page_actions:
    #     prompt.append(
    #         f"So far, you have already performed the following actions on the page:\n{turn_history.current_page_actions[1]}"
    #     )

    if browser_page.page.url != "about:blank":
        prompt.append(
            f"The webpage {browser_page.page.url} is open. Carefully analyze the HTML, and based on the HTML contents, determine the next action to take to help the user get closer to achieving their task. The HTML of the current webpage is:\n```"
            + browser_page.simplified_html
            + "\n```"
        )
    else:
        prompt.append(
            "Currently, the browser is empty. You must begin by navigating to a url. Think about how a real human would start to perform the task."
        )

    prompt.append(
        "Analyze the HTML and return your Observations, Reasoning, and Action."
    )

    return "\n\n".join(textwrap.dedent(text) for text in prompt)


with sync_playwright() as playwright:
    chromium = playwright.chromium
    browser = chromium.launch(headless=False)
    page = browser.new_page()
    page.set_default_timeout(5000)
    turn_history = TurnHistory(turns=[])
    gemini_usage = GeminiUsage()

    for i in range(50):
        available_actions = [
            ClickElementByIdAction,
            FillTextByIdAction,
            SelectOptionsByIdAction,
            GoToUrlAction,
        ]
        print(f"-------------Action {i}-----------------")
        browser_page = BrowserPage.construct(page=page)
        prompt = fmt_browser_agent_prompt(
            task="Order a large Pepperoni Pizza from Dominos delivered to 75 Harrison St, San Francisco 94107",
            available_actions=available_actions,
            turn_history=turn_history,
            browser_page=browser_page,
        )
        print(f"Prompt:\n{prompt}")

        llm_output = call_gemini(prompt, gemini_usage=gemini_usage)
        # llm_output = call_openai(prompt)

        cprint(f"\n\nLLM Output:\n{llm_output}", "green")

        turn: Turn = Turn.construct(prompt, available_actions, llm_output, browser_page)
        turn_history.save_turn(turn)

        try:
            turn.execute_actions()
        except Exception as e:
            pass

    browser.close()
