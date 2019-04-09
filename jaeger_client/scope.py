

class Scope():
    """A scope formalizes the activation and deactivation of a :class:`Span`,
    usually from a CPU standpoint. Many times a :class:`Span` will be extant
    (in that :meth:`Span.finish()` has not been called) despite being in a
    non-runnable state from a CPU/scheduler standpoint. For instance, a
    :class:`Span` representing the client side of an RPC will be unfinished but
    blocked on IO while the RPC is still outstanding. A scope defines when a
    given :class:`Span` is scheduled and on the path.
    :param manager: the :class:`ScopeManager` that created this :class:`Scope`.
    :type manager: ScopeManager
    :param span: the :class:`Span` used for this :class:`Scope`.
    :type span: Span
    """
    def __init__(self, manager, span, close_on_finish=True):
        """Initializes a scope for *span*."""
        self._manager = manager
        self._span = span
        self.__close_on_finish = close_on_finish


    @property
    def span(self):
        """Returns the :class:`Span` wrapped by this :class:`Scope`.
        :rtype: Span
        """
        return self._span

    @property
    def manager(self):
        """Returns the :class:`ScopeManager` that created this :class:`Scope`.
        :rtype: ScopeManager
        """
        return self._manager

    def close(self):
        """Marks the end of the active period for this :class:`Scope`, updating
        :attr:`ScopeManager.active` in the process.
        NOTE: Calling this method more than once on a single :class:`Scope`
        leads to undefined behavior.
        """
        if not self.__close_on_finish:
            self._manager.active = None

    def __enter__(self):
        """Allows :class:`Scope` to be used inside a Python Context Manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Calls :meth:`close()` when the execution is outside the Python
        Context Manager.
        If exception has occurred during execution, it is automatically logged
        and added as a tag to the :class:`Span`.
        :attr:`~operation.ext.tags.ERROR` will also be set to `True`.
        """
        self.span._on_error(exc_type, exc_val, exc_tb)
        self.close()