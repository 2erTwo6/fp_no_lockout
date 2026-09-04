# FP No Lockout

解除 HyperOS 指纹「失败次数过多」锁定机制 (5 次失败 → 30 秒定时锁 / 累计 20 次 → 永久锁)。
适用于指纹 HAL 在 **mfp-daemon** 里做锁定计数的机型。

> 适配机型: Redmi `dash` (2602BRT18C), HyperOS 3.0 / Android 16, 指纹方案为高通超薄屏下超声波 (Goodix `goodix_us2`)。
> 其他机型需要重新逆向适配, 见 [补丁原理](#补丁原理)。

## 解决什么问题

距离传感器故障时口袋防误触失效, 屏幕在口袋里亮起、指纹被随机触碰, 累计 5 次失败即触发
「指纹尝试次数过多」, 连带人脸解锁一并被禁, 只能密码解锁。本补丁在 **HAL 源头** 让锁定状态机
永远无法进入 TIMED / PERMANENT 状态, 错误提示与人脸连带锁定自然消失, 误触只表现为普通的
「不匹配」抖动。

## 安装

- KernelSU 管理器 / Magisk / TWRP 刷入 `fp_no_lockout_v1.0.zip`
- 或命令行: `ksud module install fp_no_lockout_v1.0.zip`
- 重启生效; 验证: `md5sum /odm/bin/hw/mfp-daemon` 应为
  `b070144e292963eafccd2d6083f3ce87` (补丁版)

内置安全机制:

1. **OTA 防呆** — 开机时校验 `/odm/bin/hw/mfp-daemon` 原版 md5, 系统更新后二进制变化则自动跳过
2. **开关** — `su -c 'setprop persist.sys.fp_nolockout.disable 1'` 后重启即恢复原生逻辑
3. 原版二进制在只读分区上从未被修改, 补丁通过 bind mount 叠加, 删模块重启即完全回滚

## 补丁原理

锁定计数不在 Android 框架层, 而在 vendor HAL (`/odm/bin/hw/mfp-daemon`) 里:

- `failed_match_count`: 每次匹配失败 +1, 达到 20 → 永久锁定
- `valid_times_per_screenlock` (对应属性 `persist.vendor.sys.fp.valid_times_per_screenlock`):
  匹配成功时重置为 5, 每次失败 -1, 归零 → 30 秒定时锁定
- 框架只被动接收 AIDL `onLockoutTimed/onLockoutPermanent` 回调再扩散给锁屏

补丁仅修改 2 条指令 (文件内偏移 = 虚拟地址):

| 偏移 | 原指令 | 补丁 | 效果 |
|---|---|---|---|
| 0x180A8 | `str w3, [x24, #728]` | `nop` | 总失败计数永不递增 → 永久锁不可能触发 |
| 0x18124 | `ldr w8, [x23, #24]` | `mov w8, #1` | 配额检查恒为有余量 → 定时锁不可能触发 |

成功解锁路径 (`clearFailedAttempts`) 与 `resetLockout` 逻辑未改动。

## 从源码构建

需要一部能取到原版 `/odm/bin/hw/mfp-daemon` 的手机 (scp/adb pull 均可):

```sh
scp phone:/odm/bin/hw/mfp-daemon mfp-daemon.stock
python3 tools/build.py --stock mfp-daemon.stock
# 产出: module/bin/mfp-daemon (补丁版) + fp_no_lockout_v1.0.zip
```

`tools/build.py` 会校验原版 md5 (`9d50fe61dfb66bac6dc5facff9f860c4`) 与补丁后 md5
(`b070144e292963eafccd2d6083f3ce87`), 不匹配即中止。

## 仓库内容

```
├── module/                    # 模块源 (可直接打包刷入)
│   ├── module.prop
│   ├── customize.sh           # 安装自检
│   ├── post-fs-data.sh        # 开机挂载补丁 (OTA 防呆 + 开关)
│   ├── uninstall.sh
│   ├── bin/mfp-daemon         # 补丁版二进制
│   └── META-INF/...           # Magisk/TWRP 安装器 stub
├── tools/build.py             # 从原版二进制生成补丁并打包 zip
└── fp_no_lockout_v1.0.zip     # 已打包的刷入包
```

## 技术要点 (踩坑记录)

- `/odm` 为 erofs 只读分区, 通过 bind mount 系统无痕叠加, 不触碰 dm-verity
- 直接 bind mount `/data` 上的文件会因 **nosuid_transition** (Android 15+ process2 类检查)
  导致 init execv 被拒: 必须先挂一个**不带 nosuid 的 tmpfs** 作为补丁文件中转
- `/data` 上的文件必须 `chmod 755` (无执行位时连 root 也无法 exec)
- 框架层 `LockoutFrameworkImpl` (AOSP 5/20 计数) 只挂在 HIDL 适配路径, AIDL HAL 机型无效,
  计数必须去 HAL 里找: `strings mfp-daemon | grep -i lockout` 是很好的起点

## 免责声明

仅供个人设备研究与自定义, 由此带来的安全权衡 (锁定保护被关闭) 由使用者自行承担。