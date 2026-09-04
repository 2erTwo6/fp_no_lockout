#!/system/bin/sh
# FP No Lockout: bind-mount patched mfp-daemon over /odm/bin/hw/mfp-daemon
MODDIR=${0%/*}
LOGTAG="FP_NoLockout"

# kill switch
if [ "$(getprop persist.sys.fp_nolockout.disable)" = "1" ]; then
  log -t $LOGTAG "disabled via prop, skipping"
  exit 0
fi

# wait for /odm to be available (max ~10s)
n=0
while [ ! -f /odm/bin/hw/mfp-daemon ] && [ $n -lt 100 ]; do
  sleep 0.1; n=$((n+1))
done
[ -f /odm/bin/hw/mfp-daemon ] || { log -t $LOGTAG "target missing, skip"; exit 1; }

# failsafe: only patch the known stock binary (OTA guard)
CUR_MD5=$(md5sum /odm/bin/hw/mfp-daemon | cut -d' ' -f1)
if [ "$CUR_MD5" != "9d50fe61dfb66bac6dc5facff9f860c4" ]; then
  log -t $LOGTAG "stock md5 mismatch ($CUR_MD5), not patching (OTA?)"
  exit 0
fi

WORK=/data/local/tmp/fpmod
# clean up any leftovers (idempotent re-run)
umount /odm/bin/hw/mfp-daemon 2>/dev/null
umount $WORK 2>/dev/null
mkdir -p $WORK
mount -t tmpfs -o mode=755,uid=0,gid=0 tmpfs $WORK || exit 1
cp "$MODDIR/bin/mfp-daemon" $WORK/mfp-daemon || exit 1
chmod 755 $WORK/mfp-daemon
chcon u:object_r:hal_fingerprint_default_exec:s0 $WORK/mfp-daemon
# bind mount BEFORE late_start services (mfp-daemon) start
mount -o bind $WORK/mfp-daemon /odm/bin/hw/mfp-daemon && \
  log -t $LOGTAG "patched mfp-daemon mounted" || \
  log -t $LOGTAG "mount FAILED"
