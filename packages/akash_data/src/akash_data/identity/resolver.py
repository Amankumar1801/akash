"""Identity layer: query -> canonical AstronomicalObject (+ cross-match evidence).

Flow: parse -> local alias lookup -> SIMBAD (name/alias/cone) -> ambiguity check ->
Gaia DR3 anchor (alias from SIMBAD, else proper-motion-propagated cone match) -> persist.
Ambiguity is surfaced (AmbiguousIdentity), never silently resolved.
"""

from __future__ import annotations

from akash_core.errors import AmbiguousIdentity, ObjectNotFound
from akash_core.schemas import AstronomicalObject, CrossmatchLink, ObjectAlias

from ..identifiers import ParsedIdentifier, parse_identifier
from ..positions import clear_winner
from ..providers.gaia import GaiaProvider
from ..providers.simbad import SimbadClient, SimbadObject
from ..storage import MetadataRepo

COORD_RADIUS_ARCSEC = 5.0
GAIA_MATCH_RADIUS_ARCSEC = 3.0
_KNOWN_ALIAS = ("TIC", "KIC", "GAIA_DR3", "GAIA_DR2", "KOI", "TOI", "SDSS")


def _alias_from_simbad_id(raw: str) -> ObjectAlias:
    try:
        p = parse_identifier(raw)
    except Exception:
        p = None
    if p and p.kind == "alias" and p.namespace in _KNOWN_ALIAS and p.identifier:
        return ObjectAlias(namespace=p.namespace, identifier=p.identifier, source="simbad")
    return ObjectAlias(namespace="SIMBAD", identifier=" ".join(raw.split()), source="simbad")


class Resolver:
    def __init__(self, repo: MetadataRepo, simbad: SimbadClient, gaia: GaiaProvider | None) -> None:
        self.repo, self.simbad, self.gaia = repo, simbad, gaia

    def resolve(self, query: str) -> AstronomicalObject:
        p = parse_identifier(query)
        if p.kind == "alias" and p.namespace and p.identifier:
            if cached := self.repo.find_by_alias(p.namespace, p.identifier):
                return cached
        cand = self._simbad_candidates(p)
        if not cand:
            raise ObjectNotFound(f"no object found for {query!r}")
        chosen = self._pick(p, cand)
        return self._build_and_persist(chosen)

    # ---- internals ----
    def _simbad_candidates(self, p: ParsedIdentifier) -> list[SimbadObject]:
        if p.kind == "coords":
            assert p.ra_deg is not None and p.dec_deg is not None
            return self.simbad.cone(p.ra_deg, p.dec_deg, COORD_RADIUS_ARCSEC)
        ident = p.simbad_form if p.kind == "alias" else (p.identifier or p.raw)
        return self.simbad.by_identifier(ident)

    def _pick(self, p: ParsedIdentifier, cand: list[SimbadObject]) -> SimbadObject:
        if p.kind == "coords":
            seps = [c.separation_arcsec for c in cand]  # already sorted
            if not clear_winner(seps):
                raise AmbiguousIdentity(
                    f"{len(cand)} objects near the given position; specify an identifier",
                    [c.main_id for c in cand],
                )
            return cand[0]
        if len(cand) > 1:
            raise AmbiguousIdentity(
                f"{p.raw!r} matches {len(cand)} objects", [c.main_id for c in cand]
            )
        return cand[0]

    def _build_and_persist(self, s: SimbadObject) -> AstronomicalObject:
        aliases = {(a.namespace, a.identifier): a
                   for a in map(_alias_from_simbad_id, self.simbad.identifiers(s.oid))}
        aliases.setdefault(("SIMBAD", s.main_id), ObjectAlias(
            namespace="SIMBAD", identifier=s.main_id, source="simbad"))

        # reuse an existing object if any alias is already known (keeps identity stable)
        for (ns, ident) in list(aliases):
            if existing := self.repo.find_by_alias(ns, ident):
                return existing

        obj = AstronomicalObject(
            ra_deg=s.ra % 360.0, dec_deg=s.dec, epoch=2000.0,
            pm_ra_mas_yr=s.pmra, pm_dec_mas_yr=s.pmdec, parallax_mas=s.parallax,
            canonical_name=s.main_id, anchor_namespace="POSITION",
        )
        links: list[CrossmatchLink] = []

        gaia_alias = next((a for a in aliases.values() if a.namespace == "GAIA_DR3"), None)
        if gaia_alias:
            obj = obj.model_copy(update={"anchor_namespace": "GAIA_DR3"})
            links.append(CrossmatchLink(
                object_id=obj.object_id, other_namespace="GAIA_DR3",
                other_identifier=gaia_alias.identifier, separation_arcsec=0.0,
                method="simbad_alias"))
        elif self.gaia is not None:
            rows, _ = self.gaia.cone_for_object_epoch(
                s.ra, s.dec, s.pmra, s.pmdec, 2000.0, GAIA_MATCH_RADIUS_ARCSEC)
            if rows:
                seps = [r["_sep_arcsec"] for r in rows]
                ambiguous = not clear_winner(seps)
                best = rows[0]
                links.append(CrossmatchLink(
                    object_id=obj.object_id, other_namespace="GAIA_DR3",
                    other_identifier=str(best["source_id"]), separation_arcsec=seps[0],
                    method="gaia_cone_pm_propagated", ambiguous=ambiguous,
                    n_candidates=len(rows)))
                if not ambiguous:
                    aliases[("GAIA_DR3", str(best["source_id"]))] = ObjectAlias(
                        namespace="GAIA_DR3", identifier=str(best["source_id"]),
                        source="gaia_crossmatch", confidence=0.9 if len(rows) == 1 else 0.7)
                    obj = obj.model_copy(update={"anchor_namespace": "GAIA_DR3"})

        obj = obj.model_copy(update={"aliases": list(aliases.values())})
        self.repo.save_object(obj)
        for ln in links:
            self.repo.add_link(ln)
        return obj
