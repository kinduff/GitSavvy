from collections import deque
from contextlib import contextmanager
from itertools import chain, takewhile

import sublime
import sublime_plugin


from GitSavvy.core.fns import pairwise
from GitSavvy.core.utils import flash


__all__ = (
    "gs_next_hunk",
    "gs_prev_hunk",
)


MYPY = False
if MYPY:
    from typing import Iterable, Iterator, List, TypeVar
    T = TypeVar("T")

    Point = int
    Row = int


LINE_DISTANCE_BETWEEN_EDITS = 2


class gs_next_hunk(sublime_plugin.TextCommand):
    def is_enabled(self):
        return len(self.view.sel()) > 0

    def run(self, edit):
        view = self.view
        if not jump_to_hunk(view, True):
            flash(view, "No hunk to jump to")


class gs_prev_hunk(sublime_plugin.TextCommand):
    def is_enabled(self):
        return len(self.view.sel()) > 0

    def run(self, edit):
        view = self.view
        if not jump_to_hunk(view, False):
            flash(view, "No hunk to jump to")


def jump_to_hunk(view, forwards):
    # type: (sublime.View, bool) -> bool
    try:
        with restore_sel_and_viewport(view):
            mod = (
                next(modifications_per_hunk(view))
                if forwards
                else last(modifications_per_hunk(view, forwards=False))
            )
    except StopIteration:
        return False
    else:
        mark_and_show_line_start(view, mod)
        return True


def mark_and_show_line_start(view, region):
    # type: (sublime.View, sublime.Region) -> None
    line = view.line(region)
    r = sublime.Region(line.a)
    set_sel(view, [r])
    show_region(view, r)


def modifications_per_hunk(view, forwards=True):
    # type: (sublime.View, bool) -> Iterator[sublime.Region]
    jump_positions = pairwise(chain(
        [cur_pos(view)], all_modifications(view, forwards)
    ))
    yield next(
        b for a, b in jump_positions
        if line_distance(view, a, b) >= LINE_DISTANCE_BETWEEN_EDITS
    )
    yield from (
        b for a, b in takewhile(
            lambda a_b: line_distance(view, *a_b) < LINE_DISTANCE_BETWEEN_EDITS,
            jump_positions
        )
    )


def all_modifications(view, forwards=True):
    # type: (sublime.View, bool) -> Iterator[sublime.Region]
    method = "next_modification" if forwards else "prev_modification"
    return take_while_unique(jump(view, method))


def jump(view, method):
    # type: (sublime.View, str) -> Iterator[sublime.Region]
    while True:
        view.run_command(method)
        yield cur_pos(view)


def line_distance(view, a, b):
    # type: (sublime.View, sublime.Region, sublime.Region) -> int
    if a.contains(b) or b.contains(a):
        return 0
    a, b = sorted((a, b), key=lambda region: region.begin())

    # If a region `a` already contains a trailing "\n" just using
    # `view.line(a)` will not strip this newline character but
    # `split_by_newlines` does.
    # E.g. for a region `(1136, 1253)` `split_by_newlines` last region
    # is                `(1214, 1252)`
    #                              ^
    a_end = view.split_by_newlines(a)[-1].end()
    b_start = b.begin()
    return abs(row_on_pt(view, a_end) - row_on_pt(view, b_start))


def row_on_pt(view, pt):
    # type: (sublime.View, Point) -> Row
    return view.rowcol(pt)[0]


def set_sel(view, selection):
    # type: (sublime.View, List[sublime.Region]) -> None
    sel = view.sel()
    sel.clear()
    sel.add_all(selection)


@contextmanager
def restore_sel_and_viewport(view):
    # type: (sublime.View) -> Iterator[None]
    frozen_sel = [s for s in view.sel()]
    vp = view.viewport_position()
    try:
        yield
    finally:
        set_sel(view, frozen_sel)
        view.set_viewport_position(vp)


def show_region(view, region, context=5):
    # type: (sublime.View, sublime.Region, int) -> None
    row_a, _ = view.rowcol(region.begin())
    row_b, _ = view.rowcol(region.end())
    adjusted_section = sublime.Region(
        # `text_point` is permissive and normalizes negative rows
        view.text_point(row_a - context, 0),
        view.text_point(row_b + context, 0)
    )
    view.show(adjusted_section, False)


def cur_pos(view):
    # type: (sublime.View) -> sublime.Region
    return view.sel()[0]


def take_while_unique(iterable):
    # type: (Iterable[T]) -> Iterator[T]
    seen = []
    for item in iterable:
        if item in seen:
            break
        seen.append(item)
        yield item


def last(iterable):
    # type: (Iterable[T]) -> T
    try:
        return deque(iterable, maxlen=1)[0]
    except IndexError as e:
        raise StopIteration from e