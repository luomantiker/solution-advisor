# M1-A-R1 验收记录

实现不可变分析器配置版本、发布/历史/回滚审计接口与 PostgreSQL Worker 容量租约；管理页使用 sessionStorage Token，不显示原始 JSON。M4-A/M4-B 仍未接入 X5 编译、板卡或 REAL。

迁移：`0003_config_leases`。回归：pytest、Vue 构建、diff 检查通过；生产 Compose 需执行升级后验证。
