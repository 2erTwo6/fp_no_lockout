ui_print "************************************"
ui_print "  FP No Lockout (mfp-daemon patch)"
ui_print "  Author: 2erTwo6"
ui_print "************************************"
ui_print "- 目标: HyperOS goodix_us2 指纹 HAL (mfp-daemon)"
ui_print "- 效果: 指纹失败次数锁定 (5次定时/20次永久) 永不触发"
ui_print "- 需 KernelSU / Magisk / APatch, 支持 bind mount"
ui_print " "
# 安装器差异: Magisk/KSU 导出 MODDIR; APatch 只导出 AP_MODULE 且 cwd=/dev/tmp
[ -n "$MODDIR" ] || MODDIR="$MODPATH"
if [ -z "$MODDIR" ] && [ -n "$AP_MODULE" ]; then
  for d in /data/adb/modules_update/"$AP_MODULE" /data/adb/modules/"$AP_MODULE"; do
    [ -d "$d" ] && MODDIR="$d" && break
  done
fi
CONF="$MODDIR/versions.conf"
SUPPORTED=""
[ -f "$CONF" ] && SUPPORTED=$(awk '!/^#/ { printf "%s ", $1 }' "$CONF")
ui_print "- 已适配原版 HAL: $SUPPORTED"
if [ ! -f /odm/bin/hw/mfp-daemon ]; then
  ui_print "! 警告: 未找到 /odm/bin/hw/mfp-daemon"
  ui_print "! 本模块可能不适用于此机型/ROM"
else
  CUR_MD5=$(md5sum /odm/bin/hw/mfp-daemon | cut -d' ' -f1)
  ui_print "- 当前 HAL md5: $CUR_MD5"
  if [ -f "$CONF" ] && grep -q "^$CUR_MD5 " "$CONF"; then
    ui_print "- 匹配: 本 ROM 已适配, 重启后生效"
  else
    ui_print "! 注意: 当前原版 md5 不在适配列表中"
    ui_print "! 开机时将自动跳过补丁 (安全回退, 保持原生逻辑)"
    ui_print "! 如系统已更新, 用新版 /odm/bin/hw/mfp-daemon 重新构建即可"
  fi
fi
# 安装器不保留 zip 内模式位 (APatch 会全部落成 0644), 显式补齐执行位
if [ -d "$MODDIR" ]; then
  ui_print "- 修复权限: $MODDIR"
  chmod 0755 "$MODDIR" 2>/dev/null
  chmod 0644 "$MODDIR/module.prop" "$MODDIR/versions.conf" 2>/dev/null
  chmod 0755 "$MODDIR/post-fs-data.sh" "$MODDIR/uninstall.sh" 2>/dev/null
  chmod 0755 "$MODDIR/bin" 2>/dev/null
  for f in "$MODDIR"/bin/*; do
    [ -f "$f" ] && chmod 0755 "$f"
  done
  ls -l "$MODDIR" "$MODDIR"/bin 2>/dev/null | while read -r l; do ui_print "  $l"; done
else
  ui_print "! 未能定位模块目录 (MODDIR 为空), 请手动执行:"
  ui_print "!   chmod 755 /data/adb/modules*/fp_no_lockout/post-fs-data.sh"
  ui_print "!   chmod 755 /data/adb/modules*/fp_no_lockout/bin/*"
fi
ui_print "- 安装完成, 重启后生效"
ui_print "- 关闭开关: setprop persist.sys.fp_nolockout.disable 1"
