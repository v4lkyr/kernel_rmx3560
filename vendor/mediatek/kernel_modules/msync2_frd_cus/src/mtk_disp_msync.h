/*
 * Copyright (c) 2021 MediaTek Inc.
 */

#ifndef __MTK_DISP_MSYNC_H__
#define __MTK_DISP_MSYNC_H__

struct msync_level {
	unsigned int level_id;
	unsigned int level_fps;
	unsigned int max_fps;
	unsigned int min_fps;
};

int fpsgo2msync_hint_frameinfo(unsigned int render_tid, unsigned int reader_bufID,
		unsigned int target_fps, unsigned long q2q_time, unsigned long q2q_time2);
int mtk_drm_get_target_fps(unsigned int vrefresh, unsigned int atomic_fps);
int mtk_sync_multi_te_level_decision(void *level_tb, unsigned int te_type,
	unsigned int target_fps, unsigned int *fps_level,
	unsigned int *min_fps, unsigned long x_time);
int mtk_sync_slow_descent(unsigned int fps_level, unsigned int fps_level_old,
		unsigned int delay_frame_num);

extern int (*fpsgo2msync_hint_frameinfo_fp)(unsigned int render_tid, unsigned int reader_bufID,
		unsigned int target_fps, unsigned long q2q_time, unsigned long q2q_time2);
extern int (*mtk_drm_get_target_fps_fp)(unsigned int vrefresh, unsigned int atomic_fps);
/*
 * This kernel (realme GT Neo 3 / MT6895, Android 12) exports a single
 * "te_level_decision" hook instead of a separate multi-TE one.  The prebuilt
 * mtk_disp_msync.o exports the multi-TE entry point; both variants are built
 * from identical code (verified by disassembly), so the prebuilt entry point
 * is hooked up to the single hook this kernel provides.
 */
extern int (*mtk_sync_te_level_decision_fp)(void *level_tb, unsigned int te_type,
	unsigned int target_fps, unsigned int *fps_level,
	unsigned int *min_fps, unsigned long x_time);
extern int (*mtk_sync_slow_descent_fp)(unsigned int fps_level, unsigned int fps_level_old,
		unsigned int delay_frame_num);
#endif
