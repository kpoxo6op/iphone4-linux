#!/bin/sh
# n90-firewall: load the phone's firewall and report its state.
#
#   n90-firewall load     modules, ruleset and network settings; safe to repeat
#   n90-firewall status   writes /run/net/firewall and /run/net/blocked for Soy
#   n90-firewall check    load once if missing, then status (the Wi-Fi keeper)
#
# The laptop's boot pass (kernel/n90-net/deploy.py) leaves the modules and
# the kernel they were built for in /opt/net, nft in /usr/sbin and the rules
# in /etc/n90/firewall.nft, and loads it before the Wi-Fi driver. The Wi-Fi
# keeper checks it before joining a network and every 20 s after.
#
# Modules built for another kernel can share its version string and still
# crash it, so they load only into the kernel recorded in /opt/net/kernel.
# Without them the phone stays on Wi-Fi unprotected, as it was before, and
# says so: "Off" on the screen and an entry in the journal.
export PATH=/bin:/sbin:/usr/bin:/usr/sbin
DIR=/opt/net
RULES=/etc/n90/firewall.nft
mkdir -p /run/net

say() { echo "$(date '+%F %T') $*" >> /run/net/firewall.log; }

loaded() { nft list table inet n90 >/dev/null 2>&1; }

status() {
	if loaded; then
		echo On > /run/net/firewall
		nft list counter inet n90 blocked 2>/dev/null |
			sed -n 's/.*packets \([0-9]*\).*/\1/p' > /run/net/blocked
	else
		echo Off > /run/net/firewall
		echo "—" > /run/net/blocked
	fi
}

# The phone is a host, not a router: it takes no ICMP redirects and sends none.
settings() {
	for f in /proc/sys/net/ipv4/conf/*/accept_redirects \
		/proc/sys/net/ipv4/conf/*/send_redirects \
		/proc/sys/net/ipv6/conf/*/accept_redirects; do
		echo 0 > "$f"
	done
}

journal() { echo "{\"t\":$(date +%s),\"e\":\"firewall\",\"state\":\"$1\"}" >> /run/soy/journal.jsonl; }

failed() {
	say "not loaded: $1"
	: > /run/net/failed
	journal off
	return 1
}

load() {
	[ "$(uname -v)" = "$(cat $DIR/kernel 2>/dev/null)" ] ||
		{ failed "the modules are for another kernel"; return; }
	for m in nfnetlink nf_tables nf_defrag_ipv4 nf_defrag_ipv6 nf_conntrack nft_ct; do
		grep -q "^$m " /proc/modules || insmod $DIR/$m.ko ||
			{ failed "insmod $m failed"; return; }
	done
	settings
	out=$(nft -f $RULES 2>&1) || { failed "$out"; return; }
	rm -f /run/net/failed
	say "loaded"
	journal on
}

case "$1" in
load)
	load
	rc=$?
	status
	exit $rc ;;
status)
	status ;;
check)
	# One attempt per boot, so a kernel without the modules is not retried
	# every 20 s; an explicit load tries again.
	[ -e /run/net/failed ] || loaded || load
	status ;;
*)
	echo "usage: n90-firewall load|status|check" >&2
	exit 2 ;;
esac
