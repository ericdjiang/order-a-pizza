from bs4 import BeautifulSoup, element, NavigableString, Comment
import re
from typing import Dict, Tuple
import difflib
from playwright.sync_api import Page, sync_playwright


def remove_hidden_elements(soup, page: Page = None):
    # Remove input elements with type="hidden"
    for hidden_input in soup.find_all("input", {"type": "hidden"}):
        hidden_input.decompose()

    # Remove elements with inline CSS display:none or visibility:hidden
    for hidden_via_css in soup.find_all(
        style=lambda value: value
        and (
            "display:none" in value.replace(" ", "")
            or "visibility:hidden" in value.replace(" ", "")
        )
    ):
        hidden_via_css.decompose()

    # Remove elements with classes or ids that commonly indicate hidden content
    # Adjust the patterns according to your needs
    common_hidden_patterns = ["hidden", "d-none", "invisible", "display-none"]
    for hidden_class_or_id in soup.find_all(
        attrs={
            "class": re.compile("|".join(common_hidden_patterns), re.I),
        },
    ) + soup.find_all(
        attrs={
            "id": re.compile("|".join(common_hidden_patterns), re.I),
        },
    ):
        # Sometimes the element will have an inline overwrite style
        if "style" in hidden_class_or_id and not "display:block" in hidden_class_or_id[
            "style"
        ].replace(" ", ""):
            hidden_class_or_id.decompose()

    # Remove elements with aria-hidden="true"
    for aria_hidden in soup.find_all(attrs={"aria-hidden": "true"}):
        aria_hidden.decompose()

    # Optional: Remove comments as they are not visible
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    return soup


def is_necessary_attribute(tag_name, attr_name):
    # Define necessary attributes for specific tags
    necessary_attrs = {
        "a": ["title", "name"],  # href
        "img": ["alt", "title"],  # src
        "iframe": ["title"],  # src
        "link": ["rel"],  # href
        "input": [
            "type",
            "name",
            "placeholder",
            "value",
            "checked",
            "disabled",
            "readonly",
            "required",
            "autocomplete",
        ],
        "textarea": [
            "name",
            "placeholder",
            "rows",
            "cols",
            "disabled",
            "readonly",
            "required",
        ],
    }

    # General attributes that are usually considered necessary
    general_necessary_attrs = [
        "id",
        "role",
        "title",
        "type",
        "name",
        # "aria-label",
        # "aria-labelledby",
        # "aria-describedby",
    ]
    # allowed_attrs = ["id", "title", "type", "role", "value", "aria-label", "name"]

    # # Preserve test attributes
    # if (
    # attr_name.startswith("aria-")
    # or attr_name.startswith("data-test")
    # or attr_name.startswith("data-testid")
    # or attr_name.startswith("data-qa")
    # or attr_name.startswith("data-quid")
    # ):
    # return True

    # Check if the attribute is necessary for the tag or generally necessary
    return (
        attr_name in necessary_attrs.get(tag_name, [])
        or attr_name in general_necessary_attrs
    )


def delete_unnecessary_attributes(tag):
    # List of attributes to remove
    attrs_to_remove = [
        attr for attr in tag.attrs if not is_necessary_attribute(tag.name, attr)
    ]

    # Remove the unnecessary attributes
    for attr in attrs_to_remove:
        del tag.attrs[attr]


def collapse_tag(tag):
    if not isinstance(tag, element.Tag):
        # print("Skipping non-tag", tag)
        return

    parent = tag.parent
    children = tag.contents

    tag_contains_text = False
    child_tag_count = 0
    for child in children:
        if isinstance(child, NavigableString) and child.strip() != "":
            tag_contains_text = True
        elif isinstance(child, element.Tag):
            child_tag_count += 1

    if (
        tag.name not in ("body", "img", "a", "input", "textarea", "button", "iframe")
        and not tag.has_attr("aria-label")
        and not tag_contains_text
        and child_tag_count <= 1
    ):
        tag.unwrap()
        children = parent.contents

    for child in children:
        collapse_tag(child)


def get_id_to_xpath_dict(html: str) -> Dict[str, str]:
    """
    Generate XPaths and map them to ids in a single traversal.
    """
    soup = BeautifulSoup(html, "lxml")
    id_to_xpath = {}
    stack = [(soup, "")]  # Tuple of (element, xpath)

    while stack:
        current, xpath = stack.pop()
        if current.name is not None:
            # Generate the xpath segment for the current element
            if current.parent is not None:
                siblings = [
                    sib for sib in current.parent.children if sib.name == current.name
                ]
                count = siblings.index(current) + 1
                xpath_segment = (
                    f"{current.name}[{count}]" if len(siblings) > 1 else current.name
                )
                xpath = f"{xpath}/{xpath_segment}"

            if current.has_attr("id"):
                id_to_xpath[current["id"]] = xpath

            # Reverse the order of children to maintain the correct order when popping from the stack
            children = [
                (child, xpath) for child in current.children if child.name is not None
            ]
            stack.extend(reversed(children))

    return id_to_xpath


def simplify_html(
    html, collapse_tags: bool = False, page: Page = None
) -> Tuple[BeautifulSoup, Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    id_to_xpath_dict = {}

    curr_id = 1
    for tag in soup.find_all(True):
        if isinstance(tag, element.Tag) and tag.name in [
            "a",
            "button",
            "input",
            "textarea",
        ]:
            if "id" not in tag.attrs or len(tag["id"]) == 0:
                if "name" in tag.attrs:
                    tag["id"] = tag["name"]
                else:
                    tag["id"] = curr_id

            curr_id += 1

    id_to_xpath_dict = get_id_to_xpath_dict(soup.prettify(formatter="minimal"))

    soup = remove_hidden_elements(soup, page)

    for script in soup(
        ["head", "script", "style", "link", "template", "meta"]
    ):  # Add "link" to remove external CSS
        script.decompose()

    if collapse_tags:
        inline_tags = soup.find_all(["span", "b", "i", "strong", "u"])
        for inline_tag in inline_tags:
            inline_tag.unwrap()

    if collapse_tags:
        body = soup.find("body")
        collapse_tag(body)

    for tag in soup.find_all(True):
        delete_unnecessary_attributes(tag)

    return soup, id_to_xpath_dict


def sanitize_html_for_diffing(html) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup(["head", "script", "style", "link", "template", "meta"]):
        script.decompose()

    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    for tag in soup.find_all(True):
        attrs_to_delete = ["tabindex"]
        for attr in attrs_to_delete:
            if attr in tag.attrs:
                del tag.attrs[attr]

    return soup


def html_diff(html1, html2):
    differ = difflib.Differ()
    diff = differ.compare(html1.strip().splitlines(), html2.strip().splitlines())
    # Filter out lines that haven't changed
    # filtered_diff = [
    #     line for line in diff if line.startswith("-") or line.startswith("+")
    # ]
    filtered_diff = []
    for line in diff:
        # Only include lines that indicate the addition or removal of elements
        if line.startswith("- ") or line.startswith("+ "):
            filtered_diff.append(line)
    return "\n".join(filtered_diff)
