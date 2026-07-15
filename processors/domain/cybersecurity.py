"""
Cybersecurity domain module — extracts security-specific signals.

Signals detected:
  - cve_mention: CVE-YYYY-NNNNN pattern
  - breach_report: "breach", "leaked", "exposed database"
  - vulnerability: "RCE", "XSS", "SQLi", "0day", "privilege escalation"
  - malware_mention: "malware", "ransomware", "trojan", "backdoor"
  - patch_urgency: "patch now", "critical update", "actively exploited"
  - compliance: "GDPR", "SOC2", "HIPAA", "PCI-DSS", "ISO 27001"
  - incident_response: "IR plan", "forensics", "incident response"
  - threat_actor: "APT", "threat group", "actor", "campaign"
  - defensive_tool: "EDR", "XDR", "SIEM", "IDS", "IPS", "WAF"
  - offensive_tool: "exploit", "payload", "shellcode", "C2"
"""
from __future__ import annotations
import re
from core.models import ProcessedItem
from processors.domain.base import BaseDomainModule


_SECURITY_PATTERNS: list[tuple[str, str, int]] = [
    # Critical (HIGH)
    ("cve_mention", r"\bCVE[- ]?\d{4}[- ]?\d{4,7}\b", 3),
    ("breach_report", r"\b(data breach|breached|leaked (data|database)|exposed (database|records|credentials))\b", 3),
    ("patch_urgency", r"\b(patch (now|immediately)|critical (update|patch)|actively exploited|zero[- ]?day|0day)\b", 3),
    ("ransomware", r"\b(ransomware|encrypt(?:ed|ion) (attack|incident)|ransom note)\b", 3),

    # High severity
    ("vulnerability_rce", r"\b(rce|remote code execution|arbitrary code execution)\b", 3),
    ("vulnerability_sqli", r"\b(sqli|sql injection|sql injection)\b", 2),
    ("vulnerability_xss", r"\b(xss|cross[- ]?site scripting)\b", 2),
    ("vulnerability_auth", r"\b(auth bypass|authentication bypass|privilege escalation|privesc)\b", 2),
    ("threat_actor", r"\b(APT\d+|advanced persistent threat|threat (actor|group)|campaign (by|attributed))\b", 2),

    # Medium
    ("malware_mention", r"\b(malware|trojan|backdoor|rootkit|botnet|c2|command and control)\b", 2),
    ("compliance_gdpr", r"\bGDPR\b", 2),
    ("compliance_soc2", r"\bSOC[\s-]?2\b", 2),
    ("compliance_hipaa", r"\bHIPAA\b", 2),
    ("compliance_pci", r"\bPCI[- ]?DSS\b", 2),
    ("compliance_iso", r"\bISO[\s-]?27001\b", 2),

    # Lower
    ("defensive_tool", r"\b(EDR|XDR|SIEM|IDS|IPS|WAF|SOAR|threat intelligence platform)\b", 1),
    ("offensive_tool", r"\b(exploit|payload|shellcode|reverse shell|metasploit|burp suite|nmap)\b", 1),
    ("incident_response", r"\b(incident response|IR plan|forensics|dfir|digital forensics)\b", 1),
    ("bug_bounty", r"\b(bug bounty|bounty program|responsible disclosure|hall of fame)\b", 1),
]


class CybersecurityDomainModule(BaseDomainModule):
    domain_name = "cybersecurity"

    def extract(self, item: ProcessedItem) -> dict:
        text = f"{item.title or ''} {item.body or ''}"
        if not text.strip():
            return {"signals": [], "severity": "none", "entities": {}}

        signals: list[str] = []
        severity_score = 0
        entities: dict = {}

        for signal_name, pattern, weight in _SECURITY_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            if matches:
                signals.append(signal_name)
                severity_score += weight
                # Save specific matches as entities
                if signal_name == "cve_mention":
                    entities["cves"] = list(set(m if isinstance(m, str) else m[0] for m in matches))[:5]
                elif signal_name == "compliance_gdpr":
                    entities["compliance_frameworks"] = entities.get("compliance_frameworks", []) + ["GDPR"]
                elif signal_name == "compliance_soc2":
                    entities["compliance_frameworks"] = entities.get("compliance_frameworks", []) + ["SOC2"]
                elif signal_name == "compliance_hipaa":
                    entities["compliance_frameworks"] = entities.get("compliance_frameworks", []) + ["HIPAA"]

        # Dedupe compliance frameworks
        if "compliance_frameworks" in entities:
            entities["compliance_frameworks"] = list(set(entities["compliance_frameworks"]))

        # Severity
        if severity_score >= 6:
            severity = "high"
        elif severity_score >= 3:
            severity = "medium"
        elif severity_score >= 1:
            severity = "low"
        else:
            severity = "none"

        return {
            "signals": signals,
            "severity": severity,
            "severity_score": severity_score,
            "entities": entities,
        }
