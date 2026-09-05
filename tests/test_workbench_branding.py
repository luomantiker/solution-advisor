from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workbench_brand_help_and_manual_claim_copy_are_versioned():
    app = (ROOT / "frontend/src/App.vue").read_text()
    admin_page = (ROOT / "frontend/src/pages/AdminPage.vue").read_text()
    workbench = (ROOT / "frontend/src/components/AdminWorkbench.vue").read_text()
    app_shell = (ROOT / "frontend/src/components/AppShell.vue").read_text()
    help_content = (ROOT / "frontend/src/help.ts").read_text()
    stylesheet = (ROOT / "frontend/src/style.css").read_text()
    assert "realthon-logo-mark.png" in app
    assert "AppShell" in app and "aux-panel" in app and "sidebar-collapsed" in app_shell
    assert "HELP_VERSION" in app and "SUPER_ADMIN" in help_content and "普通用户边界" in help_content
    assert "手动释放会清理本次接入资料" in help_content
    assert "#0d2748" in stylesheet
    assert "AdminWorkbench" in admin_page
    assert "onMounted(()=>{void refresh()" in workbench
    assert "后端权威 Workbench ViewModel" in workbench
    for component in ("AppShell.vue", "PageHeader.vue", "MetricCard.vue", "SectionCard.vue", "StatusBadge.vue", "SegmentTabs.vue", "EmptyState.vue", "SidePanel.vue", "ConfirmDialog.vue"):
        assert (ROOT / "frontend/src/components" / component).is_file()
    for retired_term in ("续租", "倒计时", "自动超时", "自动释放"):
        assert retired_term not in help_content
    candidate_copy = workbench.split('<article class="workbench-lane integrating">', 1)[1].split('</article>', 1)[0]
    assert "认领人手动释放或超级管理员处理后才会变更" in workbench
    for retired_term in ("续租", "倒计时", "自动超时", "自动释放"):
        assert retired_term not in candidate_copy


def test_realthon_logo_is_a_checked_in_binary_asset():
    asset = ROOT / "frontend/src/assets/realthon-logo-mark.png"
    assert asset.is_file()
    assert asset.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
