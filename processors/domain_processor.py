"""
Domain Processor — runs all configured domain modules as a single processor.

Wraps SaaS / Cybersecurity / Ecommerce / etc. modules so they appear as
one processor in the pipeline. Each enabled domain module scans every
item and tags it with domain-specific signals in
`item.metadata["domain_signals"][<domain_name>]`.

The Strategy Engine can then prefer decisions aligned with the user's
active domain (set in config).
"""
from __future__ import annotations
from core.models import ProcessedItem
from core.logger import get_logger
from processors.base import BaseProcessor
from processors.domain.saas import SaaSDomainModule
from processors.domain.cybersecurity import CybersecurityDomainModule
from processors.domain.ecommerce import EcommerceDomainModule


class DomainProcessor(BaseProcessor):
    name = "domain"

    def __init__(self, config: dict | None = None):
        super().__init__(config)
        self._modules: list = []
        saas_cfg = self._config.get("saas", {})
        if saas_cfg.get("enabled", True):
            self._modules.append(SaaSDomainModule(saas_cfg))
        sec_cfg = self._config.get("cybersecurity", {})
        if sec_cfg.get("enabled", True):
            self._modules.append(CybersecurityDomainModule(sec_cfg))
        ecom_cfg = self._config.get("ecommerce", {})
        if ecom_cfg.get("enabled", True):
            self._modules.append(EcommerceDomainModule(ecom_cfg))

    def _process(self, items: list[ProcessedItem]) -> list[ProcessedItem]:
        if not self._modules:
            self._logger.info("No domain modules enabled — skipping")
            return items

        for module in self._modules:
            items = module.process(items)

        # Build summary
        domain_counts: dict[str, int] = {}
        for item in items:
            signals = item.metadata.get("domain_signals", {})
            for domain_name, sig_data in signals.items():
                if sig_data.get("signals"):
                    domain_counts[domain_name] = domain_counts.get(domain_name, 0) + 1

        self._logger.info(
            f"Domain processor: {len(self._modules)} modules ran, items tagged: {domain_counts}",
            extra=domain_counts,
        )
        return items
