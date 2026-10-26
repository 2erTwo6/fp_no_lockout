#!/system/bin/sh
# FP No Lockout: bind-mount the patched mfp-daemon over /odm/bin/hw/mfp-daemon
#
# The stock HAL differs per ROM, so module/bin holds one patched binary per
# supported build and versions.conf maps <stock md5> -> <patched binary>.
# At boot we hash the real /odm binary and pick the matching patched one.
# Unknown md5 (after an OTA, for example) => skip, the stock HAL runs unchanged.
MODDIR=${0%/*}
LOGTAG="FP_NoLockout"
TARGET=/odm/bin/hw/mfp-daemon
MODPROP=/data/adb/modules/fp_no_lockout/module.prop

log_msg() { log -t $LOGTAG "$1"; }

# surface state in the KernelSU/Magisk module list (atomic replace of module.prop)
note() {
  [ -f "$MODPROP" ] || return 0
  sed '/^description=/d' "$MODPROP" > "$MODPROP.tmp" 2>/dev/null || return 0
  echo "description=$1" >> "$MODPROP.tmp" || return 0
  mv "$MODPROP.tmp" "$MODPROP" 2>/dev/null
}

# kill switch
if [ "$(getprop persist.sys.fp_nolockout.disable)" = "1" ]; then
  log_msg "disabled via prop, skipping"
  note "Disabled via persist.sys.fp_nolockout.disable=1, stock HAL active"
  exit 0
fi

# wait for /odm to be available (max ~10s)
n=0
while [ ! -f $TARGET ] && [ $n -lt 100 ]; do
  sleep 0.1; n=$((n+1))
done
[ -f $TARGET ] || { log_msg "target missing, skip"; exit 1; }

# OTA failsafe: only patch a stock HAL we have a build for
CUR_MD5=$(md5sum $TARGET | cut -d' ' -f1)
CONF="$MODDIR/versions.conf"
PATCHED=""
[ -f "$CONF" ] && PATCHED=$(awk -v m="$CUR_MD5" 'index($0, m " ") == 1 { print $2; exit }' "$CONF")

if [ -z "$PATCHED" ]; then
  log_msg "no patch for stock md5 $CUR_MD5 (new ROM?), not patching"
  note "Inactive: unsupported mfp-daemon md5 $CUR_MD5 (system updated?). Stock HAL untouched."
  exit 0
fi
[ -f "$MODDIR/bin/$PATCHED" ] || { log_msg "missing $MODDIR/bin/$PATCHED"; exit 1; }

WORK=/data/local/tmp/fpmod
# clean up any leftovers (idempotent re-run)
umount $TARGET 2>/dev/null
umount $WORK 2>/dev/null
mkdir -p $WORK
# a nosuid tmpfs would trip the Android 15+ nosuid_transition check on execv
mount -t tmpfs -o mode=755,uid=0,gid=0 tmpfs $WORK || exit 1
cp "$MODDIR/bin/$PATCHED" $WORK/mfp-daemon || exit 1
chmod 755 $WORK/mfp-daemon
chcon u:object_r:hal_fingerprint_default_exec:s0 $WORK/mfp-daemon 2>/dev/null
# bind mount BEFORE late_start services (mfp-daemon) start
if mount -o bind $WORK/mfp-daemon $TARGET; then
  log_msg "patched mfp-daemon mounted ($PATCHED, stock $CUR_MD5)"
  note "Active: mfp-daemon patched ($PATCHED) for stock $CUR_MD5. Timed and permanent lockout disabled."
else
  log_msg "mount FAILED"
  note "Failed to mount patched mfp-daemon, see logcat -b all -s FP_NoLockout"
fi
