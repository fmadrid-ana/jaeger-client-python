#!/Users/fmadrid/.virtualenvs/jaeger-client-python/bin/python

from jaeger_client import Tracer, Config
from jaeger_client.reporter import LoggingReporter, Reporter, CompositeReporter
from jaeger_client.sampler import ConstSampler
from jaeger_client.gunicorn_worker import TornadoWorker
import logging, sys, os 

from tornado.gen import coroutine
from tornado.web import Application, RequestHandler
from tornado.ioloop import IOLoop

logger = logging.getLogger('')
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler(sys.stdout))

def do_jaeger(ioloop=None):
  logger.info('initialize called')
  if 'JAEGER_AGENT_HOST' not in os.environ:
    os.environ['JAEGER_AGENT_HOST'] = 'localhost'
  if 'JAEGER_AGENT_PORT' not in os.environ:
    os.environ['JAEGER_AGENT_PORT'] = '6831'
  config = Config({
    'service_name': 'jaeger',
    'enabled': True,
    'logging': True,
    'propegation': 'b3',
    'sampler': {'type': 'const', 'param': True}
  })
  logger.info('what the hell is going on!')
  t = config.initialize_tracer(io_loop=ioloop)

  for _ in range(100):
    with t.start_active_span('hello world') as scope:
      scope.span.log_kv({'hello world': True})
      with t.start_child_span(scope.span, 'enis envy') as child_span:
        child_span.log_kv({'why am i reporting things': False})
      t.report_span(scope.span)
  logger.info('initialized!')


if __name__ == '__main__':
  do_jaeger(ioloop=IOLoop.instance())