from __future__ import absolute_import

from .span import Span, SpanContext
from .scope import Scope


class ScopeManager(object):
    """The :class:`ScopeManager` interface abstracts both the activation of
    a :class:`Span` and access to an active :class:`Span`/:class:`Scope`.
    """
    def __init__(self, span=None, scope=None):
        # TODO: `tracer` should not be None, but we don't have a reference;
        # should we move the NOOP SpanContext, Span, Scope to somewhere
        # else so that they're globally reachable?
        self._span = span if span else Span(None, SpanContext(), 'None')
        self._scope = scope if scope else Scope(self, self._span)

    def activate(self, span, finish_on_close):
        """Makes a :class:`Span` active.
        :param span: the :class:`Span` that should become active.
        :param finish_on_close: whether :class:`Span` should be automatically
            finished when :meth:`Scope.close()` is called.
        :rtype: Scope
        :return: a :class:`Scope` to control the end of the active period for
            *span*. It is a programming error to neglect to call
            :meth:`Scope.close()` on the returned instance.
        """
        return self._scope

    @property
    def active(self):
        """Returns the currently active :class:`Scope` which can be used to access the
        currently active :attr:`Scope.span`.
        If there is a non-null :class:`Scope`, its wrapped :class:`Span`
        becomes an implicit parent of any newly-created :class:`Span` at
        :meth:`Tracer.start_active_span()` time.
        :rtype: Scope
        :return: the :class:`Scope` that is active, or ``None`` if not
            available.
        """
        return self._scope