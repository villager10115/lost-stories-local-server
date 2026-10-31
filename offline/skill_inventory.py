"""Inventory card and KMF skill definitions from extracted MasterData."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


PLACEHOLDER = re.compile(r"%s([1-9])([1-5])")


def _stable(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _add_unique(mapping, identity, value, kind):
    if identity is None:
        raise ValueError("Missing %s ID" % kind)
    if identity in mapping and _stable(mapping[identity]) != _stable(value):
        raise ValueError("Conflicting definition for %s %r" % (kind, identity))
    mapping[identity] = value


def collect(cards, customizations):
    card_skills = {}
    kmf_skills = {}
    card_refs = []
    kmf_refs = []
    feature_ids = set()
    feature_refs = 0
    for card in cards:
        for slot in ("cardSkill1", "cardSkill2", "cardSkill3", "cardSkill4"):
            skill = card.get(slot)
            if not isinstance(skill, dict):
                continue
            identity = skill.get("cardSkillId")
            _add_unique(card_skills, identity, skill, "card skill")
            card_refs.append({
                "cardId": card.get("cardId"),
                "slot": slot,
                "skillId": identity,
            })
        features = card.get("cardFeatureList") or []
        feature_refs += len(features)
        for feature in features:
            if isinstance(feature, dict) and feature.get("cardFeatureId") is not None:
                feature_ids.add(feature["cardFeatureId"])
    for customization in customizations:
        skill = customization.get("knightmareFrameSkill")
        if not isinstance(skill, dict):
            continue
        identity = skill.get("knightmareFrameSkillId")
        _add_unique(kmf_skills, identity, skill, "KMF skill")
        kmf_refs.append({
            "knightmareFrameId": customization.get("knightmareFrameId"),
            "knightmareFrameCustomizeId": customization.get(
                "knightmareFrameCustomizeId"
            ),
            "skillId": identity,
        })
    return {
        "card_skills": card_skills,
        "kmf_skills": kmf_skills,
        "card_refs": card_refs,
        "kmf_refs": kmf_refs,
        "feature_refs": feature_refs,
        "feature_ids": sorted(feature_ids),
    }


def expand_description(skill, level=1):
    text = skill.get("description") or ""
    if level < 1 or level > 5:
        raise ValueError("Skill level must be from 1 to 5")

    def replace(match):
        affector = match.group(1)
        parameter = match.group(2)
        value = skill.get("affector%sParameters%s" % (affector, parameter))
        return match.group(0) if value is None else str(value)

    return PLACEHOLDER.sub(replace, text)


def _affector_codes(skill):
    result = []
    for index in range(1, 10):
        detail = skill.get("affector%s" % index)
        if isinstance(detail, dict) and detail.get("affectorDetail"):
            code = detail["affectorDetail"].get("affectorCode")
            if code:
                result.append(code)
    return result


def build(source, output):
    source = Path(source)
    output = Path(output)
    if output.exists():
        raise FileExistsError("Refusing to overwrite an existing skill inventory")
    data = json.loads(source.read_text(encoding="utf-8"))
    cards = data.get("cardList")
    customizations = data.get("knightmareFrameCustomizeList")
    if not isinstance(cards, list) or not isinstance(customizations, list):
        raise ValueError("Missing cardList or knightmareFrameCustomizeList")
    collected = collect(cards, customizations)

    card_classes = Counter(
        skill.get("cardSkillClass", "") for skill in collected["card_skills"].values()
    )
    card_activations = Counter(
        skill.get("activateType", "") for skill in collected["card_skills"].values()
    )
    kmf_classes = Counter(
        skill.get("knightmareFrameSkillClass", "")
        for skill in collected["kmf_skills"].values()
    )
    kmf_activations = Counter(
        skill.get("activateType", "") for skill in collected["kmf_skills"].values()
    )
    card_affectors = Counter(
        code
        for skill in collected["card_skills"].values()
        for code in _affector_codes(skill)
    )
    kmf_affectors = Counter(
        code
        for skill in collected["kmf_skills"].values()
        for code in _affector_codes(skill)
    )
    status = {
        "source": str(source.resolve()),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "card_count": len(cards),
        "kmf_customization_count": len(customizations),
        "unique_card_skills": len(collected["card_skills"]),
        "unique_kmf_skills": len(collected["kmf_skills"]),
        "card_skill_references": len(collected["card_refs"]),
        "kmf_skill_references": len(collected["kmf_refs"]),
        "feature_references": collected["feature_refs"],
        "unique_feature_ids": len(collected["feature_ids"]),
        "card_skill_classes": dict(card_classes.most_common()),
        "card_activate_types": dict(card_activations.most_common()),
        "kmf_skill_classes": dict(kmf_classes.most_common()),
        "kmf_activate_types": dict(kmf_activations.most_common()),
        "card_affector_codes": dict(card_affectors.most_common()),
        "kmf_affector_codes": dict(kmf_affectors.most_common()),
        "description_placeholders": sorted({
            match.group(0)
            for skill in collected["card_skills"].values()
            for match in PLACEHOLDER.finditer(skill.get("description") or "")
        } | {
            match.group(0)
            for skill in collected["kmf_skills"].values()
            for match in PLACEHOLDER.finditer(skill.get("description") or "")
        }),
    }
    output.mkdir(parents=True)
    (output / "card-skills.json").write_text(
        json.dumps(collected["card_skills"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "kmf-skills.json").write_text(
        json.dumps(collected["kmf_skills"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output / "references.json").write_text(json.dumps({
        "card": collected["card_refs"],
        "kmf": collected["kmf_refs"],
        "featureIds": collected["feature_ids"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "summary.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.source, args.output)
    print(json.dumps({
        "unique_card_skills": result["unique_card_skills"],
        "unique_kmf_skills": result["unique_kmf_skills"],
        "card_skill_classes": result["card_skill_classes"],
        "card_activate_types": result["card_activate_types"],
        "kmf_activate_types": result["kmf_activate_types"],
        "feature_references": result["feature_references"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
