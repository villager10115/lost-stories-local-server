"""Deploy the merged eight-module enhancement repair with guarded rollback."""
from argparse import ArgumentParser
from pathlib import Path

from deploy_battle_release import run


SOURCE_FILES = (
    "offline/deploy_enhancement_all_modules.py",
    "offline/verify_enhancement_all_modules.py",
    "offline/server.py",
    "offline/new_account_page.py",
    "offline/preserved_pages.py",
    "offline/test_server.py",
    "offline/test_new_account_page.py",
    "offline/test_costume_page_contract.js",
    "offline/test_local_unavailable_links.js",
    "offline/test_local_kmf_lifecycle.js",
    "offline/test_local_kmf_strength.js",
    "offline/test_kmf_management_render.cjs",
    "offline/test_kmf_strength_render.cjs",
    "stateful_server/cgls/app.py",
    "stateful_server/cgls/battle_data.py",
    "stateful_server/cgls/cosmetic_models.py",
    "stateful_server/cgls/cosmetics.py",
    "stateful_server/cgls/db.py",
    "stateful_server/cgls/kmf_color.py",
    "stateful_server/cgls/kmf_enforce.py",
    "stateful_server/cgls/kmf_management.py",
    "stateful_server/cgls/kmf_management_models.py",
    "stateful_server/cgls/kmf_rules.py",
    "stateful_server/cgls/models.py",
    "stateful_server/cgls/progression.py",
    "stateful_server/tests/test_api.py",
    "stateful_server/tests/test_battles.py",
    "stateful_server/tests/test_card_progression.py",
    "stateful_server/tests/test_costumes.py",
    "stateful_server/tests/test_kmf_color.py",
    "stateful_server/tests/test_kmf_enforce.py",
    "stateful_server/tests/test_kmf_management.py",
    "stateful_server/tests/test_pilot_feature.py",
    "stateful_server/tests/test_progression.py",
)

WEB_FILES = (
    "web/js/carrying/CarryingTop.js",
    "web/js/coloring/KmfColoring.js",
    "web/js/kmf/KmfDevelopment.js",
    "web/js/kmf/KmfDismantle.js",
    "web/js/local/LocalEnhancementPage.js",
    "web/js/local/LocalKmfLifecyclePage.js",
    "web/js/local/LocalKmfStrength.js",
    "web/js/local/LocalUnavailableLinks.js",
)


def main():
    parser = ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("D:/codegeass"))
    parser.add_argument(
        "--package", type=Path, default=Path("D:/LostStories_Japanese"))
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args()
    run(
        args.source.resolve(),
        args.package.resolve(),
        args.backup.resolve(),
        deploy=args.deploy,
        report_name="ENHANCEMENT_ALL_MODULES_20261031.md",
        receipt_name="enhancement-all-modules-deployment.json",
        report_source=args.source.resolve()
        / "ENHANCEMENT_ALL_MODULES_20261031.md",
        files=SOURCE_FILES,
        web_files=WEB_FILES,
    )


if __name__ == "__main__":
    main()
