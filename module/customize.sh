ui_print "************************************"
ui_print "  FP No Lockout (mfp-daemon patch)"
ui_print "  Author: 2erTwo6"
ui_print "************************************"
ui_print "- 目标: HyperOS goodix_us2 指纹 HAL (mfp-daemon)"
ui_print "- 效果: 指纹失败次数锁定 (5次定时/20次永久) 永不触发"
ui_print "- 需 KernelSU / Magisk 支持 bind mount"
ui_print " "
if [ ! -f /odm/bin/hw/mfp-daemon ]; then
  ui_print "! 警告: 未找到 /odm/bin/hw/mfp-daemon"
  ui_print "! 本模块可能不适用于此机型/ROM"
else
  CUR_MD5=$(md5sum /odm/bin/hw/mfp-daemon | cut -d' ' -f1)
  ui_print "- 当前 HAL md5: $CUR_MD5"
  if [ "$CUR_MD5" != "9d50fe61dfb66bac6dc5facff9f860c4" ]; then
    ui_print "! 注意: 与适配的原版 md5 不同 (可能已 OTA)"
    ui_print "! 开机时将自动跳过补丁 (安全回退)"
  fi
fi
# KSU/Magisk 安装环境差异: MODDIR 可能为空, 权限直接由 zip 内模式保证
if [ -n "$MODDIR" ] && [ -d "$MODDIR" ]; then
  set_perm_recursive "$MODDIR" 0 0 0755 0644
  set_perm "$MODDIR/post-fs-data.sh" 0 0 0755
  set_perm "$MODDIR/uninstall.sh" 0 0 0755
fi
ui_print "- 安装完成, 重启后生效"
ui_print "- 关闭开关: setprop persist.sys.fp_nolockout.disable 1"
