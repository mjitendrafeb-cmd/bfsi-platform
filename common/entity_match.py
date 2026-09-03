"""Entity matching — maps a CRA-published company name to your entity master.

Strategy (in order):
  1. Exact match on normalized legal name or any alias  -> confidence 1.0
  2. Fuzzy match (rapidfuzz token_sort_ratio) >= 92     -> confidence 0.92+
  3. No match -> None (item is still stored, unmatched, for review)

Normalization strips the noise that breaks exact matching in Indian
corporate names: Ltd/Limited/Pvt/Private, punctuation, extra spaces.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from rapidfuzz import fuzz, process
except ModuleNotFoundError:  # offline/dev fallback; production uses rapidfuzz
    from difflib import SequenceMatcher

    class _Fuzz:
        @staticmethod
        def token_sort_ratio(a: str, b: str) -> int:
            aa = " ".join(sorted(a.split()))
            bb = " ".join(sorted(b.split()))
            return round(SequenceMatcher(None, aa, bb).ratio() * 100)

    class _Process:
        @staticmethod
        def extractOne(query, choices, scorer, score_cutoff=0):
            best = None
            for idx, choice in enumerate(choices):
                score = scorer(query, choice)
                if score >= score_cutoff and (best is None or score > best[1]):
                    best = (choice, score, idx)
            return best

    fuzz = _Fuzz()
    process = _Process()

_SUFFIXES = re.compile(
    r"\b(private|pvt|limited|ltd|co|company|india)\b\.?", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9 ]")


def normalize(name: str) -> str:
    s = name.lower().strip()
    s = _SUFFIXES.sub(" ", s)
    s = _NON_ALNUM.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Match:
    entity_id: int
    display_name: str
    confidence: float


class EntityMatcher:
    def __init__(self, entity_master_csv: Path, fuzzy_threshold: int = 92):
        self.fuzzy_threshold = fuzzy_threshold
        self._exact: dict[str, tuple[int, str]] = {}
        self._names: list[str] = []
        self._name_to_entity: dict[str, tuple[int, str]] = {}
        self._load(entity_master_csv)

    def _load(self, path: Path) -> None:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                eid = int(row["id"])
                display = row["display_name"].strip()
                names = [row["legal_name"], display]
                names += [a for a in (row.get("aliases") or "").split(";")
                          if a.strip()]
                for n in names:
                    key = normalize(n)
                    if not key:
                        continue
                    self._exact[key] = (eid, display)
                    self._names.append(key)
                    self._name_to_entity[key] = (eid, display)

    def match(self, raw_name: str) -> Match | None:
        key = normalize(raw_name)
        if not key:
            return None
        if key in self._exact:
            eid, display = self._exact[key]
            return Match(eid, display, 1.0)
        best = process.extractOne(
            key, self._names, scorer=fuzz.token_sort_ratio,
            score_cutoff=self.fuzzy_threshold)
        if best:
            matched_key, score, _ = best
            eid, display = self._name_to_entity[matched_key]
            return Match(eid, display, round(score / 100, 3))
        return None
