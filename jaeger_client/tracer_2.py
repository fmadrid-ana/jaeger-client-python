from .tracer import Tracer as Tracer_v1
from .span import Span
from .scope import Scope
from .span_context import SpanContext
from .scope_manager import ScopeManager
import time
from collections import namedtuple

from . import constants
from .metrics import Metrics, LegacyMetricsFactory
import random, os
from opentracing import Format, UnsupportedFormatException
from .codecs import TextCodec, ZipkinCodec, ZipkinSpanFormat, BinaryCodec
from .utils import local_ip
import socket, logging, sys
logger = logging.getLogger('jaeger_tracing')

class Tracer(Tracer_v1):

  def __init__(
    self, service_name, reporter, sampler, metrics=None,
    metrics_factory=None,
    trace_id_header=constants.TRACE_ID_HEADER,
    generate_128bit_trace_id=False,
    baggage_header_prefix=constants.BAGGAGE_HEADER_PREFIX,
    debug_id_header=constants.DEBUG_ID_HEADER_KEY,
    one_span_per_rpc=False, extra_codecs=None,
    tags=None,
    max_tag_value_length=constants.MAX_TAG_VALUE_LENGTH,
    throttler=None,
  ):
    self.service_name = service_name
    self.reporter = reporter
    self.sampler = sampler
    self.metrics_factory = metrics_factory or LegacyMetricsFactory(metrics or Metrics())
    self.metrics = TracerMetrics(self.metrics_factory)
    self.random = random.Random(time.time() * (os.getpid() or 1))
    self.debug_id_header = debug_id_header
    self.one_span_per_rpc = one_span_per_rpc
    self.max_tag_value_length = max_tag_value_length
    self.max_trace_id_bits = constants._max_trace_id_bits if generate_128bit_trace_id \
        else constants._max_id_bits
    self.codecs = {
        Format.TEXT_MAP: TextCodec(
            url_encoding=False,
            trace_id_header=trace_id_header,
            baggage_header_prefix=baggage_header_prefix,
            debug_id_header=debug_id_header,
        ),
        Format.HTTP_HEADERS: TextCodec(
            url_encoding=True,
            trace_id_header=trace_id_header,
            baggage_header_prefix=baggage_header_prefix,
            debug_id_header=debug_id_header,
        ),
        Format.BINARY: BinaryCodec(),
        ZipkinSpanFormat: ZipkinCodec(),
    }
    if extra_codecs:
        self.codecs.update(extra_codecs)
    self.tags = {
        constants.JAEGER_VERSION_TAG_KEY: constants.JAEGER_CLIENT_VERSION,
    }
    if tags:
        self.tags.update(tags)

    if self.tags.get(constants.JAEGER_IP_TAG_KEY) is None:
        self.tags[constants.JAEGER_IP_TAG_KEY] = local_ip()

    if self.tags.get(constants.JAEGER_HOSTNAME_TAG_KEY) is None:
        try:
            hostname = socket.gethostname()
            self.tags[constants.JAEGER_HOSTNAME_TAG_KEY] = hostname
        except socket.error:
            logger.exception('Unable to determine host name')

    self.throttler = throttler
    if self.throttler:
        client_id = random.randint(0, sys.maxsize)
        self.throttler._set_client_id(client_id)
        self.tags[constants.CLIENT_UUID_TAG_KEY] = client_id

    self.reporter.set_process(
        service_name=self.service_name,
        tags=self.tags,
        max_length=self.max_tag_value_length,
    )

    self._scope_manager = ScopeManager(span=self.start_span('main'), scope=None)
    
  @property
  def scope_manager(self):
    """Provides access to the current :class:`~opentracing.ScopeManager`.
    :rtype: :class:`~opentracing.ScopeManager`
    """
    return self._scope_manager

  @property
  def active_span(self):
    """Provides access to the the active :class:`Span`. This is a shorthand for
    :attr:`Tracer.scope_manager.active.span`, and ``None`` will be
    returned if :attr:`Scope.span` is ``None``.
    :rtype: :class:`~opentracing.Span`
    :return: the active :class:`Span`.
    """
    scope = self._scope_manager.active
    return None if scope is None else scope.span

  def start_active_span(self, operation_name, child_of=None, references=None, tags=None, start_time=None, ignore_active_span=False, finish_on_close=True):
    """
    Returns a newly started and activated :class:`Scope`.
    The returned :class:`Scope` supports with-statement contexts. For
    example::
        with tracer.start_active_span('...') as scope:
            scope.span.set_tag('http.method', 'GET')
            do_some_work()
        # Span.finish() is called as part of scope deactivation through
        # the with statement.
    It's also possible to not finish the :class:`Span` when the
    :class:`Scope` context expires::
        with tracer.start_active_span('...',
                                      finish_on_close=False) as scope:
            scope.span.set_tag('http.method', 'GET')
            do_some_work()
        # Span.finish() is not called as part of Scope deactivation as
        # `finish_on_close` is `False`.
    :param operation_name: name of the operation represented by the new
        :class:`Span` from the perspective of the current service.
    :type operation_name: str
    :param child_of: (optional) a :class:`Span` or :class:`SpanContext`
        instance representing the parent in a REFERENCE_CHILD_OF reference.
        If specified, the `references` parameter must be omitted.
    :type child_of: Span or SpanContext
    :param references: (optional) references that identify one or more
        parent :class:`SpanContext`\ s. (See the Reference documentation
        for detail).
    :type references: :obj:`list` of :class:`Reference`
    :param tags: an optional dictionary of :class:`Span` tags. The caller
        gives up ownership of that dictionary, because the :class:`Tracer`
        may use it as-is to avoid extra data copying.
    :type tags: dict
    :param start_time: an explicit :class:`Span` start time as a unix
        timestamp per :meth:`time.time()`.
    :type start_time: float
    :param ignore_active_span: (optional) an explicit flag that ignores
        the current active :class:`Scope` and creates a root :class:`Span`.
    :type ignore_active_span: bool
    :param finish_on_close: whether :class:`Span` should automatically be
        finished when :meth:`Scope.close()` is called.
    :type finish_on_close: bool
    :rtype: Scope
    :return: a :class:`Scope`, already registered via the
        :class:`ScopeManager`.
    """
    span = self.start_span(operation_name=operation_name, child_of=child_of, references=references)
    return Scope(self._scope_manager, span)

  def start_span(self,
                    operation_name=None,
                    child_of=None,
                    references=None,
                    tags=None,
                    start_time=None,
                    ignore_active_span=False):
    if ignore_active_span:
      # TODO figure out what to do with "ignore_active_span"
      pass
    else:
      span = super(Tracer, self).start_span(operation_name, child_of, references, tags, start_time)
    return span

  def start_child_span(self, parent_span, operation_name, tags=None, start_time=None):
    """A shorthand method that starts a `child_of` :class:`Span` for a given
    parent :class:`Span`.
    Equivalent to calling::
        parent_span.tracer().start_span(
            operation_name,
            references=opentracing.child_of(parent_span.context),
            tags=tags,
            start_time=start_time)
    :param parent_span: the :class:`Span` which will act as the parent in the
        returned :class:`Span`\ s child_of reference.
    :type parent_span: Span
    :param operation_name: the operation name for the child :class:`Span`
        instance
    :type operation_name: str
    :param tags: optional dict of :class:`Span` tags. The caller gives up
        ownership of that dict, because the :class:`Tracer` may use it as-is to
        avoid extra data copying.
    :type tags: dict
    :param start_time: an explicit :class:`Span` start time as a unix timestamp
        per :meth:`time.time()`.
    :type start_time: float
    :rtype: Span
    :return: an already-started :class:`Span` instance.
    """
    return parent_span.tracer.start_span(
        operation_name=operation_name,
        child_of=parent_span,
        tags=tags,
        start_time=start_time
    )


class ReferenceType(object):
    """
    A namespace for OpenTracing reference types.
    See http://opentracing.io/spec for more detail about references,
    reference types, and CHILD_OF and FOLLOWS_FROM in particular.
    """    
    CHILD_OF = 'child_of'
    FOLLOWS_FROM = 'follows_from'


# We use namedtuple since references are meant to be immutable.
# We subclass it to expose a standard docstring.
class Reference(namedtuple('Reference', ['type', 'referenced_context'])):
    """A Reference pairs a reference type with a referenced :class:`SpanContext`.
    References are used by :meth:`Tracer.start_span()` to describe the
    relationships between :class:`Span`\ s.
    :class:`Tracer` implementations must ignore references where
    referenced_context is ``None``.  This behavior allows for simpler code when
    an inbound RPC request contains no tracing information and as a result
    :meth:`Tracer.extract()` returns ``None``::
        parent_ref = tracer.extract(opentracing.HTTP_HEADERS, request.headers)
        span = tracer.start_span(
            'operation', references=child_of(parent_ref)
        )
    See :meth:`child_of` and :meth:`follows_from` helpers for creating these
    references.
    """
    pass

def child_of(referenced_context=None):
    """child_of is a helper that creates CHILD_OF References.
    :param referenced_context: the (causal parent) :class:`SpanContext` to
        reference. If ``None`` is passed, this reference must be ignored by
        the :class:`Tracer`.
    :type referenced_context: SpanContext
    :rtype: Reference
    :return: A reference suitable for ``Tracer.start_span(...,
        references=...)``
    """
    return Reference(
        type=ReferenceType.CHILD_OF,
        referenced_context=referenced_context)


def follows_from(referenced_context=None):
    """follows_from is a helper that creates FOLLOWS_FROM References.
    :param referenced_context: the (causal parent) :class:`SpanContext` to
        reference. If ``None`` is passed, this reference must be ignored by the
        :class:`Tracer`.
    :type referenced_context: SpanContext
    :rtype: Reference
    :return: A Reference suitable for ``Tracer.start_span(...,
        references=...)``
    """
    return Reference(
        type=ReferenceType.FOLLOWS_FROM,
        referenced_context=referenced_context)

class TracerMetrics(object):
  """Tracer specific metrics."""

  def __init__(self, metrics_factory):
      self.traces_started_sampled = \
          metrics_factory.create_counter(name='jaeger:traces',
                                          tags={'state': 'started', 'sampled': 'y'})
      self.traces_started_not_sampled = \
          metrics_factory.create_counter(name='jaeger:traces',
                                          tags={'state': 'started', 'sampled': 'n'})
      self.traces_joined_sampled = \
          metrics_factory.create_counter(name='jaeger:traces',
                                          tags={'state': 'joined', 'sampled': 'y'})
      self.traces_joined_not_sampled = \
          metrics_factory.create_counter(name='jaeger:traces',
                                          tags={'state': 'joined', 'sampled': 'n'})
      self.spans_started_sampled = \
          metrics_factory.create_counter(name='jaeger:started_spans', tags={'sampled': 'y'})
      self.spans_started_not_sampled = \
          metrics_factory.create_counter(name='jaeger:started_spans', tags={'sampled': 'n'})
      self.spans_finished = \
          metrics_factory.create_counter(name='jaeger:finished_spans')
