import ark_pi
import ark_pi.cli
import ark_pi.common
import ark_pi.config
import ark_pi.ingest
import ark_pi.llm_client
import ark_pi.rag
import ark_pi.web


def test_package_version() -> None:
    assert ark_pi.__version__ == "0.1.0"


def test_submodule_imports() -> None:
    assert ark_pi.cli.app is not None
    assert ark_pi.config.ArkSettings is not None
