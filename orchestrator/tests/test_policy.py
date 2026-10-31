"""Policy rules in isolation, against the shipped default policy."""

from pathlib import Path

import pytest

from orchestrator.engine.models import StageSpec
from orchestrator.policy.engine import PolicyConfigError, PolicyEngine
from orchestrator.policy.models import Action, RiskTier
from orchestrator.workspace.changes import ChangeSet, FileChange

ROOT = Path(__file__).resolve().parents[2]
POLICY = PolicyEngine.load(ROOT / "policies" / "default.yaml")
STAGE = StageSpec(id="implement", agent="coder")
JAVA = "src/main/java/App.java"

POM = """<project xmlns="http://maven.apache.org/POM/4.0.0"><dependencies>{deps}</dependencies></project>"""


def dep(group, artifact):
    return f"<dependency><groupId>{group}</groupId><artifactId>{artifact}</artifactId></dependency>"


def evaluate(files: dict[str, str], previous: dict[str, str] | None = None):
    previous = previous or {}
    cs = ChangeSet({p: FileChange(p, c, previous.get(p)) for p, c in files.items()})
    return POLICY.evaluate(cs, STAGE)


def rules_hit(decision):
    return {v.rule for v in decision.violations}


def test_clean_change_is_allowed_low_risk():
    d = evaluate({JAVA: 'class App { String greet() { return "hello"; } }'})
    assert d.action is Action.ALLOW and d.tier is RiskTier.LOW and d.violations == []


# --- security: secrets -------------------------------------------------------------------

@pytest.mark.parametrize("line", [
    'String k = "AKIAIOSFODNN7EXAMPLE";',
    'private static final String API_KEY = "s3cr3t-value-123";',
    'String t = "ghp_' + "a" * 36 + '";',
    "-----BEGIN RSA PRIVATE KEY-----",
    'String blob = "q8Zr2LpX7vN0aT4kWm9YcE1sH6uJ3bGfR5dQ";',   # random, high entropy
])
def test_secrets_are_rejected(line):
    d = evaluate({JAVA: line})
    assert d.action is Action.REJECT and "secrets" in rules_hit(d)
    assert d.violations[0].line == 1


@pytest.mark.parametrize("line", [
    'String password = "${DB_PASSWORD}";',                                   # externalized
    'String ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";',  # charset
    'String url = "https://example.com/a/long/path";',
])
def test_non_secrets_are_allowed(line):
    assert "secrets" not in rules_hit(evaluate({JAVA: line}))


def test_docs_are_excluded_from_secret_scan():
    assert evaluate({"docs/setup.md": 'api_key = "your-key-here-123"'}).action is Action.ALLOW


def test_only_added_lines_are_scanned():
    existing = 'String API_KEY = "legacy-secret-1";\n'
    d = evaluate({JAVA: existing + "int x = 1;\n"}, previous={JAVA: existing})
    assert d.action is Action.ALLOW, "pre-existing debt must not fail unrelated changes"


# --- security: dangerous code ------------------------------------------------------------

@pytest.mark.parametrize("line,label", [
    ('Runtime.getRuntime().exec(cmd);', "OS command"),
    ('stmt.executeQuery("SELECT * FROM urls WHERE code = \'" + code + "\'");', "SQL"),
    ("new ObjectInputStream(in).readObject();", "deserialization"),
    ('@CrossOrigin("*")', "CORS"),
])
def test_dangerous_code_is_rejected(line, label):
    d = evaluate({JAVA: line})
    assert "dangerous_code" in rules_hit(d) and d.action is Action.REJECT
    assert label.lower() in d.violations[0].message.lower()


def test_parameterized_sql_is_allowed():
    assert evaluate({JAVA: 'jdbc.query("SELECT * FROM urls WHERE code = ?", mapper, code);'}).action is Action.ALLOW


def test_dangerous_code_rule_only_applies_to_source():
    assert evaluate({"docs/notes.md": "never call Runtime.getRuntime().exec"}).action is Action.ALLOW


# --- compliance: PII in logs ---------------------------------------------------------------

def test_pii_in_logs_is_rejected():
    d = evaluate({JAVA: 'log.info("created by {} from {}", user.email, request.getRemoteAddr());'})
    assert "pii_logging" in rules_hit(d) and d.action is Action.REJECT


def test_non_pii_logging_is_allowed():
    assert evaluate({JAVA: 'log.info("created short code {}", code);'}).action is Action.ALLOW


# --- change control ------------------------------------------------------------------------

def test_allowlisted_dependency_is_allowed():
    pom = POM.format(deps=dep("org.springframework.boot", "spring-boot-starter-web") + dep("com.h2database", "h2"))
    assert evaluate({"url-shortener/pom.xml": pom}).action is Action.ALLOW


def test_new_unlisted_dependency_requires_approval():
    before = POM.format(deps=dep("org.springframework.boot", "spring-boot-starter-web"))
    after = POM.format(deps=dep("org.springframework.boot", "spring-boot-starter-web") + dep("com.evil", "left-pad"))
    d = evaluate({"url-shortener/pom.xml": after}, previous={"url-shortener/pom.xml": before})
    assert d.action is Action.REQUIRE_APPROVAL and d.tier is RiskTier.HIGH
    assert "com.evil:left-pad" in d.violations[0].message


def test_already_present_unlisted_dependency_is_not_reflagged():
    pom = POM.format(deps=dep("com.legacy", "thing"))
    assert evaluate({"url-shortener/pom.xml": pom + "\n"}, previous={"url-shortener/pom.xml": pom}).action is Action.ALLOW


def test_malformed_pom_requires_approval():
    assert evaluate({"url-shortener/pom.xml": "<project><dependencies>"}).action is Action.REQUIRE_APPROVAL


def test_creating_a_migration_requires_approval():
    d = evaluate({"url-shortener/src/main/resources/db/migration/V2__clicks.sql": "CREATE TABLE clicks(id INT);"})
    assert d.action is Action.REQUIRE_APPROVAL and "high_impact_paths" in rules_hit(d)


def test_config_may_be_created_but_modifying_requires_approval():
    path = "url-shortener/src/main/resources/application.yml"
    assert evaluate({path: "server:\n  port: 8080\n"}).action is Action.ALLOW
    d = evaluate({path: "server:\n  port: 9090\n"}, previous={path: "server:\n  port: 8080\n"})
    assert d.action is Action.REQUIRE_APPROVAL


def test_oversized_diff_requires_approval():
    big = "\n".join(f"int v{i} = {i};" for i in range(1600))
    d = evaluate({JAVA: big})
    assert d.action is Action.REQUIRE_APPROVAL and "diff_size" in rules_hit(d)


def test_strictest_action_wins():
    pom = POM.format(deps=dep("com.evil", "left-pad"))
    d = evaluate({"url-shortener/pom.xml": pom, JAVA: 'String API_KEY = "s3cr3t-value-123";'})
    assert d.action is Action.REJECT
    assert {v.action for v in d.violations} == {Action.REJECT, Action.REQUIRE_APPROVAL}


# --- configuration -------------------------------------------------------------------------

def test_unknown_rule_in_policy_file_is_an_error(tmp_path):
    bad = tmp_path / "p.yaml"
    bad.write_text("rules:\n  no_such_rule: {}\n")
    with pytest.raises(PolicyConfigError, match="unknown policy rule"):
        PolicyEngine.load(bad)


def test_disabled_rule_is_skipped_and_action_is_configurable(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("rules:\n  secrets: {action: block}\n  diff_size: {enabled: false}\n")
    engine = PolicyEngine.load(p)
    assert [r.name for r in engine.rules] == ["secrets"] and engine.rules[0].action is Action.BLOCK


def test_policy_hash_changes_when_policy_changes(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text("rules:\n  secrets: {}\n")
    first = PolicyEngine.load(p).policy_sha
    p.write_text("rules:\n  secrets: {action: block}\n")
    assert PolicyEngine.load(p).policy_sha != first


def test_modifying_an_existing_test_requires_approval_but_adding_one_does_not():
    path = "url-shortener/src/test/java/com/example/LinkTest.java"
    assert evaluate({path: "class LinkTest {}"}).action is Action.ALLOW
    d = evaluate({path: "class LinkTest { /* weakened */ }"}, previous={path: "class LinkTest { @Test void t() {} }"})
    assert d.action is Action.REQUIRE_APPROVAL and "high_impact_paths" in rules_hit(d)
