import logging
from typing import Optional

from robusta.core.model.base_params import NamedRegexPattern
from robusta.core.playbooks.pod_utils.crashloop_utils import get_crash_report_enrichments
from robusta.core.reporting import Finding, FindingSource, FindingSeverity, FileBlock, EmptyFileBlock
from robusta.core.reporting.base import EnrichmentType
from robusta.core.reporting.finding_subjects import PodFindingSubject
from robusta.integrations.kubernetes.autogenerated.events import PodEvent
from robusta.integrations.kubernetes.custom_models import RegexReplacementStyle


def send_crash_report(
        event: PodEvent,
        action_name: str,
        regex_replacer_patterns: Optional[NamedRegexPattern] = None,
        regex_replacement_style: Optional[RegexReplacementStyle] = None,
):
    pod = event.get_pod()

    all_statuses = pod.status.containerStatuses + pod.status.initContainerStatuses
    crashed_container_statuses = [
        container_status
        for container_status in all_statuses
        if container_status.state.waiting is not None and container_status.restartCount >= 1
    ]

    finding = Finding(
        title=f"Crashing pod {pod.metadata.name} in namespace {pod.metadata.namespace}",
        source=FindingSource.KUBERNETES_API_SERVER,
        severity=FindingSeverity.HIGH,
        aggregation_key=action_name,
        subject=PodFindingSubject(pod),
    )

    enrichments = get_crash_report_enrichments(pod)
    for enrichment in enrichments:
        finding.add_enrichment(enrichment.blocks,
                               enrichment_type=enrichment.enrichment_type,
                               title=enrichment.title)

    for container_status in crashed_container_statuses:
        try:
            container_log = pod.get_logs(
                container_status.name,
                previous=True,
                regex_replacer_patterns=regex_replacer_patterns,
                regex_replacement_style=regex_replacement_style,
            )

            if not container_log:
                log_block = EmptyFileBlock(filename=f"{pod.metadata.name}.log",
                                           remarks=f"Logs unavailable for container: {container_status.name}")
                logging.info(
                    f"could not fetch logs from container: {container_status.name}"
                )
            else:
                log_block = FileBlock(filename=f"{pod.metadata.name}.log", contents=container_log.encode())

            finding.add_enrichment([log_block],
                                   enrichment_type=EnrichmentType.text_file, title="Logs")
        except Exception:
            logging.error("Failed to get pod logs", exc_info=True)

        event.add_finding(finding)