/* SPDX-License-Identifier: GPL-2.0-only
 * Reduced regression fixture: relevant regions copied verbatim from the locked
 * upstream driver after its Linux 6.6.133 patch stack. See README.md.
 * Only surrounding kernel infrastructure is replaced by test scaffolding.
 */
#include "kernel_stubs.h"
#if defined(CONFIG_NET_MEDIATEK_HNAT) || defined(CONFIG_NET_MEDIATEK_HNAT_MODULE)
#include "mtk_hnat/nf_hnat_mtk.h"
#endif
static int mtk_wifi_num = 0;
static int mtk_rest_cnt = 0;
atomic_t eth1_in_br = ATOMIC_INIT(0);
EXPORT_SYMBOL(eth1_in_br);
struct net_device *ppd_dev;
EXPORT_SYMBOL(ppd_dev);
static int mtk_msg_level = -1;
module_param_named(msg_level, mtk_msg_level, int, 0);
MODULE_PARM_DESC(msg_level, "Message level (-1=defaults,0=none,...,16=all)");
DECLARE_COMPLETION(wait_ser_done);

static int receive(struct mtk_eth *eth, unsigned rxd4, int mac)
{
    struct { unsigned rxd4; } trxd = { rxd4 };
    int sent_ppd = 0;
    void *netdev = 0;
    if (0) {
		} else if (!MTK_HAS_CAPS(eth->soc->caps, MTK_SOC_MT7628) &&
			   !(trxd.rxd4 & RX_DMA_SPECIAL_TAG)) {
			mac = RX_DMA_GET_SPORT(trxd.rxd4) - 1;
		}

		if ( (mac == 4) || ((FIELD_GET(MTK_RXD4_PPE_CPU_REASON, trxd.rxd4)) == HIT_BIND_FORCE_TO_CPU))
		{
		
		mac = atomic_read(&eth1_in_br);
		sent_ppd = 1;
		}
		if (unlikely(mac < 0 || mac >= MTK_MAX_DEVS ||
			     !eth->netdev[mac]))
			goto release_desc;

		netdev = eth->netdev[mac];

    (void)netdev;
    return mac + sent_ppd * 10;
release_desc:
    return -1;
}

static void reset_start(struct mtk_eth *eth)
{
    int i = 0;
    (void)i;
	mtk_wed_fe_reset();
	/* Run again reset preliminary configuration in order to avoid any
	 * possible race during FE reset since it can run releasing RTNL lock.
	 */
	mtk_prepare_for_reset(eth);
	/* Trigger Wifi SER reset */
	for (i = 0; i < MTK_MAX_DEVS; i++) {
		if (!eth->netdev[i])
			continue;
		call_netdevice_notifiers(MTK_FE_START_RESET, eth->netdev[i]);
		rtnl_unlock();
		wait_for_completion_timeout(&wait_ser_done, 5000);
		rtnl_lock();
		break;
	}
	/* stop all devices to make sure that dma is properly shut down */
	for (i = 0; i < MTK_MAX_DEVS; i++) {
		if (!eth->netdev[i] || !netif_running(eth->netdev[i]))
			continue;


        normal_stops++;
    }
}

static void reset_finish(struct mtk_eth *eth)
{
    int i = 0;
    (void)i;

	mtk_wed_fe_reset_complete();
	mtk_restore_qdma_cfg(eth);
	for (i = 0; i < MTK_MAX_DEVS; i++) {
                if (!eth->netdev[i])
                        continue;
		call_netdevice_notifiers(MTK_FE_RESET_NAT_DONE, eth->netdev[i]);
		printk("[%s] HNAT reset done !\n", __func__);
		call_netdevice_notifiers(MTK_FE_RESET_DONE, eth->netdev[i]);
		printk("[%s] WiFi SER reset done !\n", __func__);
        }
	rtnl_unlock();
}


static int mtk_eth_netdevice_event(struct notifier_block *unused,
				   unsigned long event, void *ptr)
{
	switch (event) {
	case MTK_WIFI_RESET_DONE:
		mtk_rest_cnt--;
		if(!mtk_rest_cnt) {
			complete(&wait_ser_done);
			mtk_rest_cnt = mtk_wifi_num;
		}
		break;
	case MTK_WIFI_CHIP_ONLINE:
		mtk_wifi_num++;
		mtk_rest_cnt = mtk_wifi_num;
		break;
	case MTK_WIFI_CHIP_OFFLINE:
		mtk_wifi_num--;
		mtk_rest_cnt = mtk_wifi_num;
		break;
	default:
		break;
	}

	return NOTIFY_DONE;
}

struct notifier_block mtk_eth_netdevice_nb __read_mostly = {
	.notifier_call = mtk_eth_netdevice_event,
};

/* Observe normal Ethernet work and optional HNAT coordination separately. */
int main(void)
{
    int device = 1;
    struct mtk_eth eth = { .soc = &(struct soc){0}, .netdev = {&device, &device} };
    eth1_in_br = 1;
    reset_start(&eth);
    reset_finish(&eth);
    if (normal_prepares != 1 || normal_stops != 2 || normal_completions != 1 || normal_restores != 1)
        return 1;
#if defined(CONFIG_NET_MEDIATEK_HNAT) || defined(CONFIG_NET_MEDIATEK_HNAT_MODULE)
    if (receive(&eth, 0, 4) != 11 || receive(&eth, 0x16, 0) != 11)
        return 2;
    if (notifier_calls != 5 || ser_waits != 1)
        return 3;
    if (events[0] != 0x2000 || events[1] != 0x4001 || events[2] != 0x2001 ||
        events[3] != 0x4001 || events[4] != 0x2001)
        return 4;
#else
    if (receive(&eth, 0, 4) != -1 || receive(&eth, 0x16, 0) != 0)
        return 5;
    if (notifier_calls != 0 || ser_waits != 0)
        return 6;
#endif
    mtk_eth_netdevice_nb.notifier_call(0, 0x2003, 0);
    mtk_eth_netdevice_nb.notifier_call(0, 0x2002, 0);
    mtk_eth_netdevice_nb.notifier_call(0, 0x2004, 0);
#if defined(CONFIG_NET_MEDIATEK_HNAT) || defined(CONFIG_NET_MEDIATEK_HNAT_MODULE)
    if (wait_ser_done != 1 || mtk_wifi_num != 0 || mtk_rest_cnt != 0)
        return 7;
#else
    if (wait_ser_done != 0)
        return 8;
#endif
    if (receive(&eth, 0, 0) != 0 || mtk_eth_netdevice_nb.notifier_call(0, 0xffff, 0) != NOTIFY_DONE)
        return 9;
    return 0;
}
