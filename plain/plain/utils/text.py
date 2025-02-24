import re
import unicodedata

from plain.utils.functional import SimpleLazyObject, keep_lazy_text, lazy
from plain.utils.regex_helper import _lazy_re_compile

# Set up regular expressions
re_words = _lazy_re_compile(r"<[^>]+?>|([^<>\s]+)", re.S)
re_chars = _lazy_re_compile(r"<[^>]+?>|(.)", re.S)
re_tag = _lazy_re_compile(r"<(/)?(\S+?)(?:(\s*/)|\s.*?)?>", re.S)


class Truncator(SimpleLazyObject):
    """
    An object used to truncate text, either by characters or words.
    """

    def __init__(self, text):
        super().__init__(lambda: str(text))

    def add_truncation_text(self, text, truncate=None):
        if truncate is None:
            truncate = "%(truncated_text)s…"
        if "%(truncated_text)s" in truncate:
            return truncate % {"truncated_text": text}
        # The truncation text didn't contain the %(truncated_text)s string
        # replacement argument so just append it to the text.
        if text.endswith(truncate):
            # But don't append the truncation text if the current text already
            # ends in this.
            return text
        return f"{text}{truncate}"

    def chars(self, num, truncate=None, html=False):
        """
        Return the text truncated to be no longer than the specified number
        of characters.

        `truncate` specifies what should be used to notify that the string has
        been truncated, defaulting to a translatable string of an ellipsis.
        """
        self._setup()
        length = int(num)
        text = unicodedata.normalize("NFC", self._wrapped)

        # Calculate the length to truncate to (max length - end_text length)
        truncate_len = length
        for char in self.add_truncation_text("", truncate):
            if not unicodedata.combining(char):
                truncate_len -= 1
                if truncate_len == 0:
                    break
        if html:
            return self._truncate_html(length, truncate, text, truncate_len, False)
        return self._text_chars(length, truncate, text, truncate_len)

    def _text_chars(self, length, truncate, text, truncate_len):
        """Truncate a string after a certain number of chars."""
        s_len = 0
        end_index = None
        for i, char in enumerate(text):
            if unicodedata.combining(char):
                # Don't consider combining characters
                # as adding to the string length
                continue
            s_len += 1
            if end_index is None and s_len > truncate_len:
                end_index = i
            if s_len > length:
                # Return the truncated string
                return self.add_truncation_text(text[: end_index or 0], truncate)

        # Return the original string since no truncation was necessary
        return text

    def words(self, num, truncate=None, html=False):
        """
        Truncate a string after a certain number of words. `truncate` specifies
        what should be used to notify that the string has been truncated,
        defaulting to ellipsis.
        """
        self._setup()
        length = int(num)
        if html:
            return self._truncate_html(length, truncate, self._wrapped, length, True)
        return self._text_words(length, truncate)

    def _text_words(self, length, truncate):
        """
        Truncate a string after a certain number of words.

        Strip newlines in the string.
        """
        words = self._wrapped.split()
        if len(words) > length:
            words = words[:length]
            return self.add_truncation_text(" ".join(words), truncate)
        return " ".join(words)

    def _truncate_html(self, length, truncate, text, truncate_len, words):
        """
        Truncate HTML to a certain number of chars (not counting tags and
        comments), or, if words is True, then to a certain number of words.
        Close opened tags if they were correctly closed in the given HTML.

        Preserve newlines in the HTML.
        """
        if words and length <= 0:
            return ""

        html4_singlets = (
            "br",
            "col",
            "link",
            "base",
            "img",
            "param",
            "area",
            "hr",
            "input",
        )

        # Count non-HTML chars/words and keep note of open tags
        pos = 0
        end_text_pos = 0
        current_len = 0
        open_tags = []

        regex = re_words if words else re_chars

        while current_len <= length:
            m = regex.search(text, pos)
            if not m:
                # Checked through whole string
                break
            pos = m.end(0)
            if m[1]:
                # It's an actual non-HTML word or char
                current_len += 1
                if current_len == truncate_len:
                    end_text_pos = pos
                continue
            # Check for tag
            tag = re_tag.match(m[0])
            if not tag or current_len >= truncate_len:
                # Don't worry about non tags or tags after our truncate point
                continue
            closing_tag, tagname, self_closing = tag.groups()
            # Element names are always case-insensitive
            tagname = tagname.lower()
            if self_closing or tagname in html4_singlets:
                pass
            elif closing_tag:
                # Check for match in open tags list
                try:
                    i = open_tags.index(tagname)
                except ValueError:
                    pass
                else:
                    # SGML: An end tag closes, back to the matching start tag,
                    # all unclosed intervening start tags with omitted end tags
                    open_tags = open_tags[i + 1 :]
            else:
                # Add it to the start of the open tags list
                open_tags.insert(0, tagname)

        if current_len <= length:
            return text
        out = text[:end_text_pos]
        truncate_text = self.add_truncation_text("", truncate)
        if truncate_text:
            out += truncate_text
        # Close any tags still open
        for tag in open_tags:
            out += f"</{tag}>"
        # Return string
        return out


@keep_lazy_text
def slugify(value, allow_unicode=False):
    """
    Convert to ASCII if 'allow_unicode' is False. Convert spaces or repeated
    dashes to single dashes. Remove characters that aren't alphanumerics,
    underscores, or hyphens. Convert to lowercase. Also strip leading and
    trailing whitespace, dashes, and underscores.
    """
    value = str(value)
    if allow_unicode:
        value = unicodedata.normalize("NFKC", value)
    else:
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-_")


def pluralize(singular, plural, number):
    if number == 1:
        return singular
    else:
        return plural


def pluralize_lazy(singular, plural, number):
    def _lazy_number_unpickle(func, resultclass, number, kwargs):
        return lazy_number(func, resultclass, number=number, **kwargs)

    def lazy_number(func, resultclass, number=None, **kwargs):
        if isinstance(number, int):
            kwargs["number"] = number
            proxy = lazy(func, resultclass)(**kwargs)
        else:
            original_kwargs = kwargs.copy()

            class NumberAwareString(resultclass):
                def __bool__(self):
                    return bool(kwargs["singular"])

                def _get_number_value(self, values):
                    try:
                        return values[number]
                    except KeyError:
                        raise KeyError(
                            f"Your dictionary lacks key '{number}'. Please provide "
                            "it, because it is required to determine whether "
                            "string is singular or plural."
                        )

                def _translate(self, number_value):
                    kwargs["number"] = number_value
                    return func(**kwargs)

                def format(self, *args, **kwargs):
                    number_value = (
                        self._get_number_value(kwargs) if kwargs and number else args[0]
                    )
                    return self._translate(number_value).format(*args, **kwargs)

                def __mod__(self, rhs):
                    if isinstance(rhs, dict) and number:
                        number_value = self._get_number_value(rhs)
                    else:
                        number_value = rhs
                    translated = self._translate(number_value)
                    try:
                        translated %= rhs
                    except TypeError:
                        # String doesn't contain a placeholder for the number.
                        pass
                    return translated

            proxy = lazy(lambda **kwargs: NumberAwareString(), NumberAwareString)(
                **kwargs
            )
            proxy.__reduce__ = lambda: (
                _lazy_number_unpickle,
                (func, resultclass, number, original_kwargs),
            )
        return proxy

    return lazy_number(pluralize, str, singular=singular, plural=plural, number=number)
