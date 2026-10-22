#!/bin/sh
# n90-wifi-keep: bring up the BCM4329 and keep the phone on a known network.
#
# The laptop's boot pass leaves the patched modules in /opt/wifi, Apple's
# firmware and NVRAM in /lib/firmware/brcm, and /run/wifi/networks:
# "SSID<TAB>PMK" lines, keys it derived from Boris's passwords. Loading the
# driver happens here, once per boot and off the boot pass's path, so a
# failure costs Wi-Fi, not the boot.
#
# While wlan0 is not on a network: scan, join the first known network in
# range (the file is in Boris's order of preference), and hold a DHCP lease
# on it. With nothing known in range the scans back
# off from 20 s to 2 min. Routes through a link that is down are ignored,
# so the USB cable's default route stops mattering once it is unplugged.
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
NETS=/run/wifi/networks
LOG=/run/wifi/keep.log
PID=/run/wifi/udhcpc.pid
mkdir -p /run/wifi
chmod 700 /run/wifi
echo 1 > /proc/sys/net/ipv4/conf/all/ignore_routes_with_linkdown

say() { echo "$(date '+%F %T') $*" >> "$LOG"; }
journal() { echo "{\"t\":$(date +%s),\"e\":\"wifi\",\"state\":\"$1\"}" >> /run/soy/journal.jsonl; }

load() {
	[ -e /run/wifi/loaded ] && return
	: > /run/wifi/loaded
	say "loading the Wi-Fi driver"
	cd /opt/wifi || return
	for m in libarc4 cfg80211 brcmutil; do
		grep -q "^$m " /proc/modules || insmod $m.ko
	done
	grep -q "^brcmfmac " /proc/modules || { insmod brcmfmac.ko && insmod brcmfmac-wcc.ko; }
	i2cset -f -y 0 0x74 0x58 0x0b	# chip power (PMU GPIO register 0x58)
	grep -q "^sdhci_pltfm " /proc/modules || insmod sdhci-pltfm.ko
	grep -q "^sdhci_s5l8930 " /proc/modules ||
		insmod sdhci-s5l8930.ko fixed=1 max_mhz=12 single_block=1
	n=0
	while [ ! -e /sys/class/net/wlan0 ] && [ $n -lt 30 ]; do
		sleep 1
		n=$((n + 1))
	done
	[ -e /sys/class/net/wlan0 ] && say "wlan0 is up" || say "no wlan0 after 30 s"
}

dhcp_running() {
	p=; read -r p 2>/dev/null < "$PID"
	[ -n "$p" ] && [ -d "/proc/$p" ]
}

say "keep started"
wait=20 was=
while :; do
	# No known network: leave the radio off.
	if [ ! -s "$NETS" ]; then
		sleep 30
		continue
	fi
	[ -e /sys/class/net/wlan0 ] || load
	if [ ! -e /sys/class/net/wlan0 ]; then
		sleep 30
		continue
	fi
	ip link set wlan0 up 2>/dev/null
	if now=$(n90-wifi link 2>/dev/null); then
		if [ "$now" != "$was" ]; then
			say "$now"
			was=$now
		fi
		dhcp_running || udhcpc -b -R -i wlan0 -p "$PID" -x hostname:iphone4 >> "$LOG" 2>&1
		wait=20
		sleep 20
		continue
	fi
	if [ -n "$was" ]; then
		say "lost the network"
		journal lost
		was=
		dhcp_running && kill "$(cat "$PID")"
	fi
	out=$(n90-wifi join "$NETS" 2>&1)
	case $? in
	0)
		say "$out"
		journal joined
		wait=20
		continue ;;	# get an address now
	3)
		[ $wait -lt 120 ] && wait=$((wait * 2)) ;;
	*)
		say "join failed: $out" ;;
	esac
	sleep $wait
done
