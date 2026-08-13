"""The prompt widgets: choose one of a list, confirm, and free text.

These replace `fzf`. They sit **below** the `Ui` seam, so they are components with
their own tests, driven through `prompt_toolkit`'s pipe input — which is how the key
handling gets covered without a terminal.

Two behaviours the bash pickers arrived at and which are preserved:

* a single candidate is auto-selected without prompting
* bad input re-prompts instead of aborting — here, an unrecognised key is simply
  ignored and the prompt stays up, which is the windowed equivalent

## Only universally understood keys are bound

| Key | Everywhere |
|---|---|
| `↑` `↓` `Home` `End` | move |
| `Enter` | choose, or accept what you typed |
| `y` / `n` | answer a yes/no question |
| `Ctrl-C` | back out |

Nothing else. **Going back is an entry you can see, not a key you have to know**:
every choice prompt ends with a visible "Back", added by the `Ui` layer, so nothing
about leaving a prompt has to be learned or documented.

There is no `q` (it meant one thing in a choice prompt and the opposite in a text
prompt), no `j`/`k` (vim-only), and no number shortcuts (an invention of this tool).

## Escape is not bound, on purpose

See `_abandon_bindings` for the full reasoning. In short: every escape sequence
starts with Escape, so binding it makes a lone Escape ambiguous and slow — over a
second, measured — and binding it *eagerly* instead swallows the Option+Arrow
sequences that a text prompt needs for word movement. Neither is acceptable, and
neither is necessary once going back is a visible entry.
"""

from __future__ import annotations

from collections.abc import Sequence

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style

from lane.ui.seam import Abandoned, Choice

_ABANDON = object()

HINT = "↑↓ move · enter choose"
"""The whole key vocabulary, in one string. The table below the seam shows the same
one, because it binds the same keys and nothing more."""

FOOTER = f"\n  {HINT}\n"

BACK_OUT_HINT = "ctrl-c back out"
"""How to leave a free-text or confirmation prompt."""

BACK_OUT_FOOTER = f"\n  {BACK_OUT_HINT}\n"

ESCAPE_TIMEOUT = 0.05
"""How long the parser waits for the rest of an escape sequence, in seconds.

`prompt_toolkit` defaults to 0.5s. A stray Escape is not bound to anything, but it
should still not leave the prompt feeling stuck for half a second before the next
keypress is acted on. A locally typed Option+Arrow arrives as one burst in a single
read, so 50ms is generous for a real sequence.
"""

STYLE = Style.from_dict(
    {
        "picker.title": "bold",
        "picker.pointer": "#00afff bold",
        "picker.selected": "#00afff bold",
        "picker.hint": "#8a8a8a",
        "picker.footer": "#8a8a8a",
    }
)


def _abandon_bindings() -> KeyBindings:
    """Ctrl-C goes back. **Escape is deliberately not bound at all.**

    Escape cannot be made to feel right here. Every terminal escape sequence starts
    with it, so binding it makes a lone Escape ambiguous and `prompt_toolkit` must
    wait to see whether more follows — measured against the built binary, over a
    second before anything happened, which reads as "Esc does not work". Lowering the
    timeout was tried; the wait comes from binding-level ambiguity
    (`timeoutlen`), not only from the parser.

    So going back is a **visible entry** in every choice prompt instead, and Escape
    is left to mean nothing. Ctrl-C stays because it is unambiguous, instant, and
    the key every terminal user already reaches for.

    Leaving Escape unbound has a second benefit: Option+Arrow arrives as Escape then
    Left, so there is now nothing for it to trip over in a menu, and in the text
    prompt `prompt_toolkit`'s own word movement is untouched.
    """
    bindings = KeyBindings()

    @bindings.add("c-c")
    def _abandon(event: KeyPressEvent) -> None:
        event.app.exit(result=_ABANDON)

    return bindings


def _run(
    bindings: KeyBindings,
    render: object,
    *,
    erase: bool,
    input_: Input | None,
    output: Output | None,
) -> object:
    assert callable(render)
    application: Application[object] = Application(
        layout=Layout(
            HSplit(
                [
                    Window(
                        # Without this the terminal cursor sits on the first
                        # character of the prompt, which reads as if that letter
                        # were selected.
                        FormattedTextControl(render, show_cursor=False),
                        dont_extend_height=True,
                    )
                ]
            )
        ),
        key_bindings=bindings,
        style=STYLE,
        full_screen=False,
        erase_when_done=erase,
        input=input_,
        output=output,
    )
    # Not a constructor argument, so it is set on the application.
    application.ttimeoutlen = ESCAPE_TIMEOUT
    return application.run()


def pick[T](
    title: str,
    options: Sequence[Choice[T]],
    *,
    input: Input | None = None,
    output: Output | None = None,
) -> T:
    """Return the chosen value, or raise `Abandoned`.

    A lone candidate is returned without drawing anything: asking a question with
    one possible answer wastes the user's time.
    """
    if not options:
        raise Abandoned
    if len(options) == 1:
        return options[0].value

    state = {"index": 0}

    def render() -> FormattedText:
        fragments: list[tuple[str, str]] = []
        if title:
            fragments += [("class:picker.title", title), ("", "\n\n")]
        max_label_width = max(len(o.label) for o in options) if options else 0
        for position, option in enumerate(options):
            chosen = position == state["index"]
            fragments.append(("class:picker.pointer", "  ❯ " if chosen else "    "))
            padded_label = option.label.ljust(max_label_width)
            fragments.append(("class:picker.selected" if chosen else "", padded_label))
            if option.hint:
                fragments.append(("class:picker.hint", f"   {option.hint}"))
            fragments.append(("", "\n"))
        fragments.append(("class:picker.footer", FOOTER))
        return FormattedText(fragments)

    bindings = _abandon_bindings()

    @bindings.add("up")
    def _up(event: KeyPressEvent) -> None:
        del event
        state["index"] = (state["index"] - 1) % len(options)

    @bindings.add("down")
    def _down(event: KeyPressEvent) -> None:
        del event
        state["index"] = (state["index"] + 1) % len(options)

    @bindings.add("home")
    def _first(event: KeyPressEvent) -> None:
        del event
        state["index"] = 0

    @bindings.add("end")
    def _last(event: KeyPressEvent) -> None:
        del event
        state["index"] = len(options) - 1

    @bindings.add("enter")
    def _accept(event: KeyPressEvent) -> None:
        event.app.exit(result=options[state["index"]].value)

    result = _run(bindings, render, erase=True, input_=input, output=output)
    if result is _ABANDON:
        raise Abandoned
    return result  # type: ignore[return-value]


def confirm(
    title: str,
    *,
    default: bool = False,
    input: Input | None = None,
    output: Output | None = None,
) -> bool:
    """A yes/no question, answered with `y` or `n`.

    A binary question does not want an arrow picker: labelling it `[y/N]` and then
    refusing to accept `y` is worse than either option on its own. Enter takes the
    default; anything unrecognised is ignored rather than aborting.
    """
    suffix = "[Y/n]" if default else "[y/N]"

    def render() -> FormattedText:
        return FormattedText(
            [
                ("class:picker.title", f"  {title} "),
                ("class:picker.hint", suffix),
                ("class:picker.footer", BACK_OUT_FOOTER),
            ]
        )

    bindings = _abandon_bindings()

    @bindings.add("y")
    @bindings.add("Y")
    def _yes(event: KeyPressEvent) -> None:
        event.app.exit(result=True)

    @bindings.add("n")
    @bindings.add("N")
    def _no(event: KeyPressEvent) -> None:
        event.app.exit(result=False)

    @bindings.add("enter")
    def _default(event: KeyPressEvent) -> None:
        event.app.exit(result=default)

    result = _run(bindings, render, erase=False, input_=input, output=output)
    if result is _ABANDON:
        raise Abandoned
    return bool(result)


def prompt_text(
    title: str,
    *,
    default: str = "",
    input: Input | None = None,
    output: Output | None = None,
) -> str:
    """Free text, with the line editing a terminal user already expects.

    Everything `prompt_toolkit` provides as standard works here — Option+Arrow to
    move by word, Ctrl-A and Ctrl-E, Option+Backspace to delete a word — precisely
    because no custom binding is layered on top to get in the way. Esc and Ctrl-C go
    back; Enter accepts, falling back to `default` when nothing was typed.
    """
    session: PromptSession[object] = PromptSession(
        key_bindings=_abandon_bindings(),
        input=input,
        output=output,
        style=STYLE,
        bottom_toolbar=lambda: FormattedText([("class:picker.footer", BACK_OUT_HINT)]),
    )
    # PromptSession takes no such constructor argument, so it is set on the app.
    session.app.ttimeoutlen = ESCAPE_TIMEOUT
    prompt = f"{title}: " if not default else f"{title} [{default}]: "
    try:
        answer = session.prompt(prompt)
    except (KeyboardInterrupt, EOFError) as exc:
        # Ctrl-C behaves like Esc inside a prompt rather than killing the session.
        raise Abandoned from exc

    if answer is _ABANDON:
        raise Abandoned
    typed = str(answer).strip()
    return typed if typed else default
