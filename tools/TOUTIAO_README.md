# 今日头条发布功能使用说明

## 功能概述

已为 `gzh_and_tout_write.py` 添加今日头条文章发布功能，可以将生成的文章自动发布到今日头条草稿箱。

## 配置步骤

### 1. 获取今日头条 Access Token

1. 访问今日头条开放平台：https://open.toutiao.com/
2. 注册并创建应用
3. 获取 `access_token`（注意：今日头条的 access_token 有效期较长，通常为 30 天）

### 2. 配置环境变量

在你的环境中设置以下环境变量：

```bash
export TOUTIAO_ACCESS_TOKEN="你的今日头条access_token"
```

如果使用 GitHub Actions，需要在仓库的 Secrets 中添加：
- `TOUTIAO_ACCESS_TOKEN`

## 使用方法

### 命令行使用

```bash
# 生成文章并发布到今日头条
python tools/gzh_and_tout_write.py gen "美联储降息" --toutiao

# 只发布到今日头条（不发布到微信和 GitHub）
python tools/gzh_and_tout_write.py gen "美联储降息" --toutiao --no-wx --no-gh

# 同时发布到所有平台
python tools/gzh_and_tout_write.py gen "美联储降息" --toutiao
```

### GitHub Actions 使用

1. 在 Actions 页面点击 "Run workflow"
2. 输入话题
3. 勾选 "发布到今日头条" 选项
4. 点击运行

### Issue 触发

在 Issue body 中添加：
```
toutiao: true
```

## 功能特点

1. **Markdown 格式支持**：今日头条支持 Markdown 格式，文章会保持良好的排版
2. **草稿箱保存**：文章会先保存到草稿箱，你可以在今日头条后台进行最后的审核和调整
3. **自动格式转换**：代码会自动将生成的 Markdown 内容转换为今日头条支持的格式
4. **错误处理**：如果发布失败，不会影响其他平台的发布

## 注意事项

1. 今日头条的 access_token 有效期通常为 30 天，过期后需要重新获取
2. 文章会保存到草稿箱，需要手动审核后才能正式发布
3. 今日头条对内容有审核机制，请确保文章内容符合平台规范
4. 建议先在测试环境验证功能正常后再在生产环境使用

## API 参考

今日头条开放平台文档：https://open.toutiao.com/doc/

主要使用的 API：
- 文章发布接口：`POST https://open.toutiao.com/api/media/article/create/`

## 故障排查

如果发布失败，请检查：

1. `TOUTIAO_ACCESS_TOKEN` 是否正确配置
2. access_token 是否过期
3. 网络连接是否正常
4. 查看日志中的具体错误信息

## 示例输出

```
2024-03-10 10:30:00 [INFO] 今日头条: 文章已保存到草稿箱, article_id=1234567890
```

成功后会返回文章 ID，你可以在今日头条后台的草稿箱中找到该文章。
