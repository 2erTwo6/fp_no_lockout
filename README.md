# FP No Lockout

> Author: **2erTwo6** ([@2erTwo6](https://github.com/2erTwo6))

解除 HyperOS 指纹「失败次数过多」锁定机制 (5 次失败 → 30 秒定时锁 / 累计 20 次 → 永久锁)。
适用于指纹 HAL 在 **mfp-daemon** 里做锁定计数的机型。

> 适配机型: Redmi `dash` (2602BRT18C), 高通超薄屏下超声波 (Goodix `goodix_us2`)。
> 同一份模块内含多套已适配二进制, 开机时自动匹配当前 ROM:
>
> | ROM | 版本串 | 原版 HAL md5 | 补丁后 md5 |
> |---|---|---|---|
> | HyperOS 4 (Android 17) | `OS4.0.3.0.XPLCNXM` / `17OS4.0.261020.230009638.MTPECN.S` | `f943889add94013ab08e9749cc29f077` | `d6ef30b1bf6e9a1a23cef7f6172f7f88` |
> | HyperOS 3 (Android 16) | `OS3.0` | `9d50fe61dfb66bac6dc5facff9f860c4` | `b070144e292963eafccd2d6083f3ce87` |
>
> 其他机型需要重新逆向适配, 见 [补丁原理](#补丁原理) 与 [适配新 ROM](#适配新-rom)。

## 解决什么问题

距离传感器故障时口袋防误触失效, 屏幕在口袋里亮起、指纹被随机触碰, 累计 5 次失败即触发
「指纹尝试次数过多」, 连带人脸解锁一并被禁, 只能密码解锁。本补丁在 **HAL 源头** 让锁定状态机
永远无法进入 TIMED / PERMANENT 状态, 错误提示与人脸连带锁定自然消失, 误触只表现为普通的
「不匹配」抖动。

## 安装

- 直接刷 `fp_no_lockout_v1.2.zip`
- KernelSU 管理器 / Magisk / TWRP 均可, 或命令行:
  - KernelSU: `ksud module install fp_no_lockout_v1.2.zip`
  - APatch: `/data/adb/apd module install fp_no_lockout_v1.2.zip` (装完写入
    `modules_update/`, **必须重启**才替换)
- 重启生效; 验证:
  - `md5sum /odm/bin/hw/mfp-daemon` 应等于上表「补丁后 md5」中与你 ROM 对应的那行
  - `cp /proc/$(pidof mfp-daemon)/exe /data/local/tmp/r && md5sum /data/local/tmp/r`
    应得到**同一个** md5 — 这才是「真的跑起来了」的证据
  - 模块列表里 description 会显示 `Active: ...` / `Inactive: ...` 的实时状态

内置安全机制:

1. **OTA 防呆** — 开机时校验 `/odm/bin/hw/mfp-daemon` 原版 md5, 在 `versions.conf` 里找不到
   对应条目就**自动跳过** (例如系统更新后), 原生逻辑不受影响
2. **开关** — `su -c 'setprop persist.sys.fp_nolockout.disable 1'` 后重启即恢复原生逻辑
3. 原版二进制在只读分区上从未被修改, 补丁通过 bind mount 叠加, 删模块重启即完全回滚

## 补丁原理

锁定计数不在 Android 框架层, 而在 vendor HAL (`/odm/bin/hw/mfp-daemon`) 里:

- `failed_match_count`: 每次匹配失败 +1, 达到 20 → 永久锁定
- `valid_times_per_screenlock` (对应属性 `persist.vendor.sys.fp.valid_times_per_screenlock`):
  匹配成功时重置为 5, 每次失败 -1, 归零 → 30 秒定时锁定
- 框架只被动接收 AIDL `onLockoutTimed/onLockoutPermanent` 回调再扩散给锁屏

`gnu_debugdata` 里保留了符号, 两条计数路径就是:
`aidl::android::hardware::biometrics::fingerprint::Fingerprint::addFailedAttempts()`
(OS4 为 `0x17FE0`, OS3 为 `0x17FE0`, 两个版本同址同布局)。

补丁仅修改 2 条指令 (文件内偏移 = 虚拟地址, `.text` 单段 0x4000 对齐):

| 偏移 | 原指令 | 补丁 | 效果 |
|---|---|---|---|
| 0x180A8 | `str w3, [x24, #0x2d8]` | `nop` | `failed_match_count` 永不递增 → 永久锁不可能触发 |
| 0x18124 | `ldr w8, [x23, #0x18]` | `mov w8, #1` | 配额检查恒为有余量 → 定时锁不可能触发 |

成功解锁路径 (`clearFailedAttempts`) 与 `resetLockout` 逻辑未改动, 所以正常解锁后的
「清空计数」行为、以及用户主动触发的 `resetLockout` 都照旧。

> OS4.0.3.0 相对 OS3.0 的变化: 二进制重排 (体积 222504 → 222496, `.text`/`.rodata`/符号表
> 全部前移), `x_log` 被裁掉换成一个 48 字节的日志桩, `FodEngineCore::setFodAuthState` 加了
> 空指针检查。**锁定状态机本身逐条指令等价** (只有 adrp/add/bl 的相对操作数不同),
> 因此两个版本用完全相同的两条补丁, 偏移也一致。

## 从源码构建

需要一部能取到原版 `/odm/bin/hw/mfp-daemon` 的手机 (scp/adb pull 均可):

```sh
scp phone:/odm/bin/hw/mfp-daemon mfp-daemon.stock
python3 tools/build.py --stock mfp-daemon.stock
# 产出: module/bin/mfp-daemon.<版本> + fp_no_lockout_v1.2.zip
```

- 已知 ROM 自动按 md5 命中 `VERSIONS` 表, 并校验补丁后 md5
- 只重新打包 (不再改二进制) 时: `python3 tools/build.py` (读取 `module/bin` 现有文件)
- 一次打多个 ROM: 重复 `--stock` 即可, 每个版本一个补丁二进制, `versions.conf` 自动生成

## 适配新 ROM

系统更新后 md5 一定变, 但锁定代码通常没动:

```sh
scp phone:/odm/bin/hw/mfp-daemon mfp-daemon.new.stock
python3 tools/build.py --stock mfp-daemon.new.stock --scan
```

`--scan` 用结构签名定位补丁点, 而不是写死偏移, 校验项包括:

1. 全文件唯一匹配 `str w3,[x24,#0x2d8]` + `str w8,[x23,#0x18]` 这对相邻计数写入
2. 前一条是 `ldr w9,[x23,#0x18]`, 前面还有 `sub w8, w9, #1`
3. 后面紧跟 `cmp w8, #0x14` (20 次永久锁阈值) 且 `b.lt` **确实**跳到配额检查点
4. 配额检查点是指令 `ldr w8,[x23,#0x18]` 后接 `cbnz w8`

四条全过才生成补丁并打印可直接粘进 `VERSIONS` 的条目 (含新 md5)。任何一条不过就拒绝出包,
不会产出「看起来成功、实际没打上」的二进制。

## 仓库内容

```
├── module/                    # 模块源 (可直接打包刷入)
│   ├── module.prop
│   ├── versions.conf          # 原版 md5 -> 补丁二进制 (build.py 生成)
│   ├── customize.sh           # 安装自检 (打印当前 ROM 是否已适配)
│   ├── post-fs-data.sh        # 开机挂载补丁 (版本匹配 + OTA 防呆 + 开关)
│   ├── uninstall.sh
│   ├── bin/mfp-daemon.os4     # 补丁版 (HyperOS 4)
│   ├── bin/mfp-daemon.os3     # 补丁版 (HyperOS 3)
│   └── META-INF/...           # Magisk/TWRP 安装器 stub
└── tools/build.py             # 打补丁 + 打包 zip (产出 fp_no_lockout_v1.2.zip)
```

## 技术要点 (踩坑记录)

- `/odm` 为 erofs 只读分区, 通过 bind mount 系统无痕叠加, 不触碰 dm-verity
- 直接 bind mount `/data` 上的文件会因 **nosuid_transition** (Android 15+ process2 类检查)
  导致 init execv 被拒: 必须先挂一个**不带 nosuid 的 tmpfs** 作为补丁文件中转
- `/data` 上的文件必须 `chmod 755` (无执行位时连 root 也无法 exec)
- 框架层 `LockoutFrameworkImpl` (AOSP 5/20 计数) 只挂在 HIDL 适配路径, AIDL HAL 机型无效,
  计数必须去 HAL 里找: `strings mfp-daemon | grep -i lockout` 是很好的起点
- 二进制里保留的 `.gnu_debugdata` (xz 压缩的迷你符号表) 极有用:
  `xz -dc <(dd if=mfp-daemon bs=1 skip=$((0x34130)) count=7408)` 后 `readelf -sW` 就能拿到
  `addFailedAttempts` 等函数地址, 不必盲扫
- 判断「OTA 后锁定逻辑是否变了」: 用符号表对比两版二进制的函数尺寸表, 再看目标函数里
  除 `adrp/add/bl/adr` 相对操作数之外是否逐字相同
- **APatch 与 KernelSU/Magisk 的安装器差异** (v1.2 实机踩到, 已在 `customize.sh` 里兜底):
  - APatch 安装 `customize.sh` 时 **不导出 `MODDIR`**, `cwd` 是 `/dev/tmp` 且里面只有
    `module.prop`, 靠 `$0` 也拿不到模块目录; 只导出 `AP_MODULE=<id>`。
    所以自检必须用 `AP_MODULE` 拼 `modules_update/<id>` 兜底, 否则「适配列表」永远是空的
  - APatch 解压时 **丢弃 zip 内的模式位**, 所有文件落成 0644 —
    `post-fs-data.sh` 没有执行位就不会被跑, 表现为「装好了但完全不生效」且没有任何报错。
    必须在 `customize.sh` 里显式 `chmod 0755`
  - APatch 采用 staged install: 装完先进 `modules_update/` 并给旧目录打 `update` 标记,
    重启时才替换; 装完不重启等于没装
  - 老版本装过会留下 `disable` 标记, 升级时注意确认它已被清掉, 否则重启后模块仍被跳过

## 免责声明

仅供个人设备研究与自定义, 由此带来的安全权衡 (锁定保护被关闭) 由使用者自行承担。

## License

[MIT](LICENSE) © 2026 2erTwo6
