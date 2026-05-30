import json
import logging
import os
import sys
from dataclasses import dataclass

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

SERVICE_NAME = "todo-api"
LOGGER_NAME = "todo_api.requests"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if isinstance(record.msg, dict):
            return json.dumps(record.msg, separators=(",", ":"), sort_keys=True)
        return json.dumps(
            {"event_type": "application_log", "message": record.getMessage()},
            separators=(",", ":"),
            sort_keys=True,
        )


@dataclass(frozen=True)
class Observability:
    logger: logging.Logger
    request_counter: metrics.Counter
    error_counter: metrics.Counter
    request_duration: metrics.Histogram
    release: str
    environment: str
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    logger_provider: LoggerProvider | None = None

    def shutdown(self) -> None:
        if self.logger_provider is not None:
            self.logger_provider.shutdown()
        if self.meter_provider is not None:
            self.meter_provider.shutdown()
        if self.tracer_provider is not None:
            self.tracer_provider.shutdown()


def environment_value(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    return value or default


def otlp_endpoint(signal: str) -> str:
    base_endpoint = environment_value(
        "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"
    ).rstrip("/")
    return environment_value(
        f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT",
        f"{base_endpoint}/v1/{signal}",
    )


def configure_request_logger(logger_provider: LoggerProvider | None) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(JsonFormatter())
    logger.addHandler(stream_handler)

    if logger_provider is not None:
        logger.addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))
    return logger


def initialize_observability() -> Observability:
    enabled = environment_value("TODO_OTEL_ENABLED", "false").lower() == "true"
    release = environment_value("TODO_RELEASE", "local")
    environment = environment_value("TODO_ENVIRONMENT", "local")
    resource = Resource.create(
        {
            "service.name": SERVICE_NAME,
            "service.version": release,
            "deployment.environment.name": environment,
        }
    )

    if not enabled:
        meter = metrics.get_meter(SERVICE_NAME)
        return Observability(
            logger=configure_request_logger(None),
            request_counter=meter.create_counter("todo_api.http.server.requests"),
            error_counter=meter.create_counter("todo_api.http.server.errors"),
            request_duration=meter.create_histogram(
                "todo_api.http.server.duration", unit="ms"
            ),
            release=release,
            environment=environment,
        )

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint("traces")))
    )
    trace.set_tracer_provider(tracer_provider)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=otlp_endpoint("metrics")),
        export_interval_millis=1_000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=otlp_endpoint("logs")))
    )

    meter = meter_provider.get_meter(SERVICE_NAME)
    return Observability(
        logger=configure_request_logger(logger_provider),
        request_counter=meter.create_counter("todo_api.http.server.requests"),
        error_counter=meter.create_counter("todo_api.http.server.errors"),
        request_duration=meter.create_histogram(
            "todo_api.http.server.duration", unit="ms"
        ),
        release=release,
        environment=environment,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
    )


observability = initialize_observability()
