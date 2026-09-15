"""Bundle canonical repository resources in direct and sdist-derived wheels."""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        root = Path(self.root)
        resources = root / "package-resources"
        if not resources.is_dir():
            resources = root.parent
        for source, target in (("docs/contracts", "contracts_data"), ("LICENSE", "LICENSE"), ("NOTICE", "NOTICE")):
            build_data["force_include"][str(resources / source)] = f"extrio/{target}"
