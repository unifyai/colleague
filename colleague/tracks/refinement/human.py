"""Participant surface for the refinement track's browser runs.

This track's spec is deliberately drip-fed: Daniel states the procedure
once (in the attached brief), fixes the format once as feedback on the
first draft, and never restates either. A participant surface here must
add mechanics without adding memory — so the surface is the *same* every
week, and it never states the title, the column names, the amount format
or the flag rule. Those live only in Daniel's messages and attachments,
and keeping hold of them is the thing being measured.

Under the document-scale regime the mechanics are file mechanics: the
week's documents arrive as downloadable attachments on the turn, and the
deliverable is a spreadsheet the participant builds with their own tools
and hands back — in the terminal, by saving it under the session
workspace and naming its path in ``/done`` (or just leaving it there;
the newest produced file is collected). The browser workbench serves the
incoming documents for download; returning a file through the browser is
not built yet, so browser runs of this track are read-only previews
until the upload stub lands. Nothing in any of that carries a fact the
scorer checks.
"""

from __future__ import annotations

from typing import Any

WORKSPACE_BRIEF = (
    "You look after Daniel Okafor's weekly client spend report. Everything "
    "about how the report should look and what belongs in it, Daniel tells "
    "you in his messages and the files he attaches - nothing is restated "
    "here, so keep hold of what he has asked for.\n\n"
    "Each week his message arrives with the week's documents attached. "
    "Build the report with your own tools and send the finished "
    "spreadsheet back: save it in your workspace and name its path when "
    "you finish, or just leave it there - your newest produced file is "
    "what goes back to him. Ask Daniel when you need him."
)


def surface_for(request: str) -> dict[str, Any]:
    """The participant surface for one refinement turn.

    ``request`` is the office-language text of the turn — Daniel's message
    verbatim. The surface is identical every week by design; only this
    text varies, and the attachments ride the turn event itself.
    """
    return {
        "title": "Weekly client spend report",
        "brief": WORKSPACE_BRIEF,
        "request": request,
        "lookups": [],
        "actions": [],
        "deliverable": {
            "kind": "file",
            "description": (
                "One spreadsheet back to Daniel, built from the attached "
                "documents. Terminal: save it under your workspace and "
                "name its path in /done. Browser: not yet supported."
            ),
        },
        "hold": None,
        "ask": True,
    }
