/* Test scaffolding only; no HNAT symbols are defined here. */
typedef int atomic_t;
#define ATOMIC_INIT(n) (n)
#define atomic_read(p) (*(p))
#define EXPORT_SYMBOL(x)
#define module_param_named(a,b,c,d) static void *fixture_param __attribute__((unused)) = &b
#define MODULE_PARM_DESC(a,b)
#define DECLARE_COMPLETION(n) int n
#define __read_mostly
#define MTK_MAX_DEVS 3
#define MTK_SOC_MT7628 1
#define MTK_HAS_CAPS(a,b) 1
#define RX_DMA_SPECIAL_TAG 0
#define RX_DMA_GET_SPORT(x) 1
#define MTK_RXD4_PPE_CPU_REASON 0xff
#define FIELD_GET(mask,x) ((x) & (mask))
#define unlikely(x) (x)
#define NOTIFY_DONE 0
struct soc { int caps; };
struct mtk_eth { struct soc *soc; void *netdev[MTK_MAX_DEVS]; };
struct notifier_block { int (*notifier_call)(struct notifier_block *, unsigned long, void *); };
static int notifier_calls, ser_waits, normal_prepares, normal_stops, normal_completions, normal_restores;
static unsigned events[8];
static inline void call_netdevice_notifiers(unsigned event, void *dev) { events[notifier_calls++] = event; }
static inline void rtnl_unlock(void) { }
static inline void rtnl_lock(void) { }
static inline void wait_for_completion_timeout(int *completion, int timeout) { ser_waits++; }
static inline void complete(int *completion) { ++*completion; }
static inline void mtk_prepare_for_reset(struct mtk_eth *eth) { normal_prepares++; }
static inline void mtk_wed_fe_reset_complete(void) { normal_completions++; }
static inline void mtk_restore_qdma_cfg(struct mtk_eth *eth) { normal_restores++; }
static inline int netif_running(void *netdev) { return 1; }
#define printk(...) ((void)0)

static inline void mtk_wed_fe_reset(void) { }
