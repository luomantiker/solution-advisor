# S100 Worker Host 安装边界

将本目录以只读方式安装到 Worker Host 的 `/opt/solution-advisor/platform-packages/s100/`。
板端连接资料仅位于该 Host 的受限配置和密钥文件，不能写入 Git、网页、Candidate、Artifact 普通日志或任务参数。

固定容器入口为：

```text
python3 -m platform_runner execute --request /work/input/request.json --result /work/output/result.json
```

该 Runner 固定调用 `hb_compile --fast-perf --march nash-e --model …`，实际产物格式为 `s100_hbm` / `.hbm`。板端固定调用以 Host 受控配置为准；已验证 Runtime 为 `hrt_model_exec perf`，但性能仅代表版本化 fixture，不能推广到客户模型。
