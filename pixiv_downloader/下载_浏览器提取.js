/**
 * Pixiv 作品图片URL提取器 (AJAX API版) v2.0
 * ============================================
 * 在 Pixiv 任意页面 (已登录) 的浏览器Console中运行。
 * 使用 Pixiv 官方AJAX API获取作品信息，无需DOM解析，稳定可靠。
 * 
 * 支持模式:
 *   A. 作品批量下载: 设置 IDS 数组
 *   B. 作者全部作品下载: 设置 USER_ID
 * 
 * === 作品模式 (A) ===
 *   1. 打开任意 Pixiv 页面 (确保已登录)
 *   2. F12 → Console
 *   3. 修改下方 IDS 数组为你要下载的作品ID列表
 *   4. 粘贴全部代码，回车运行
 *   5. 自动下载JSON文件
 * 
 * === 作者模式 (B) ===
 *   1. 设置 USER_ID (数字字符串)
 *   2. 可选设置 MAX_AUTHOR_ARTWORKS 限制数量
 *   3. 运行 → 自动拉取作者名下所有作品 + 作者标签
 *   4. JSON包含 author.name + author.tags + 每个作品的tags
 * 
 * 输出JSON格式:
 *  作者模式: {"mode":"author","author":{"id":"","name":"","tags":[...]},
 *              "artworks":{"123":{"pages":N,"title":"","ext":"","tags":[...],"urls":[...]}}}
 *  作品模式: {"mode":"artworks","artworks":{"123":{...}}}
 */

// ============ 配置区 ============

// [A] 作品模式: 作品ID列表 (作者模式时留空)
const IDS = [
    // 示例: '134922694', '121454474'
];

// [B] 作者模式: 作者用户ID (作品模式时留空)
const USER_ID = '';

// 作者模式下最多下载作品数 (0=不限制)
const MAX_AUTHOR_ARTWORKS = 0;

// 作者标签采样作品数 (从作者前N个作品中统计标签)
const TAG_SAMPLE_COUNT = 20;

// ============ 核心函数 ============

/** 延迟工具 */
const sleep = ms => new Promise(r => setTimeout(r, ms));

/** 
 * 获取单个作品信息 (含tags) — v3: null防护 + 429重试
 * @returns {pages, title, ext, tags[], urls[]} 或 null
 */
async function getIllustInfo(illustId, retries = 3) {
    for (let attempt = 1; attempt <= retries; attempt++) {
        const resp = await fetch(`/ajax/illust/${illustId}?lang=zh`);
        // 429限流 → 等待后重试
        if (resp.status === 429) {
            const wait = attempt * 2000 + Math.random() * 1000;
            if (attempt < retries) {
                console.warn(`  ⚠️ 429限流, ${(wait/1000).toFixed(1)}s后重试(${attempt}/${retries})...`);
                await sleep(wait);
                continue;
            }
            console.error(`❌ 作品 ${illustId}: 429重试耗尽`);
            return null;
        }
        // 404 → 作品已删除, 不重试
        if (resp.status === 404) {
            return null;
        }
        const data = await resp.json();
        if (data.error) {
            console.error(`❌ 作品 ${illustId}: ${data.message}`);
            return null;
        }
        const body = data.body;
        
        // === null防护: urls.original可能为空 ===
        if (!body.urls || !body.urls.original) {
            console.warn(`  ⚠️ 作品 ${illustId}: urls.original为空 (可能是R-18需要登录态)`);
            return null;
        }
        
        const pageCount = body.pageCount;
        const ext = body.urls.original.split('.').pop().split('?')[0];
        const title = body.illustTitle || body.title || '';
        
        // 提取tags
        let tags = [];
        if (body.tags && body.tags.tags) {
            tags = body.tags.tags.map(t => t.tag || t);
        }
        const userId = body.userId || '';
        const userName = body.userName || '';
        
        // 使用API返回的original URL，替换_p0为各页
        const originalUrl = body.urls.original;
        const urls = [];
        for (let i = 0; i < pageCount; i++) {
            urls.push(originalUrl.replace(/_p0\./, `_p${i}.`));
        }
        
        return { pages: pageCount, title, ext, tags, userId, userName, urls };
    }
    return null;
}

/** 获取用户基本信息 */
async function getUserInfo(userId) {
    const resp = await fetch(`/ajax/user/${userId}?full=1&lang=zh`);
    const data = await resp.json();
    if (data.error) {
        console.error(`❌ 用户 ${userId}: ${data.message}`);
        return null;
    }
    const body = data.body;
    // 从自我介绍中提取标签 (#tag 格式)
    const comment = body.comment || '';
    const commentTags = (comment.match(/#([^\s#]+)/g) || []).map(t => t.slice(1));
    
    return {
        id: userId,
        name: body.name || '',
        comment: comment,
        commentTags: commentTags,
        followingTags: [], // 后续从profile/top填充
    };
}

/** 获取用户profile标签（关注标签） */
async function getUserProfileTags(userId) {
    try {
        const resp = await fetch(`/ajax/user/${userId}/profile/top?lang=zh`);
        const data = await resp.json();
        if (data.error) return [];
        const body = data.body;
        // profile/top 可能包含 pickup 标签
        let tags = [];
        // 尝试从followingTags或featuredTags提取
        if (body.followingTags) {
            tags = body.followingTags.map(t => typeof t === 'string' ? t : t.tag || t.name || '');
        }
        if (body.pickup && body.pickup.tags) {
            tags = tags.concat(body.pickup.tags.map(t => typeof t === 'string' ? t : t.tag || ''));
        }
        return [...new Set(tags.filter(Boolean))];
    } catch (e) {
        return [];
    }
}

/** 获取用户的所有作品ID */
async function getAllUserIllustIds(userId) {
    const allIds = [];
    let offset = 0;
    const limit = 48;
    
    while (true) {
        const resp = await fetch(`/ajax/user/${userId}/profile/all?lang=zh`);
        const data = await resp.json();
        if (data.error) {
            console.error(`❌ 获取作品列表失败: ${data.message}`);
            break;
        }
        const body = data.body;
        const illusts = body.illusts || [];
        const manga = body.manga || []; // 漫画也包含
        
        for (const key in illusts) {
            allIds.push(key);
        }
        for (const key in manga) {
            if (!allIds.includes(key)) allIds.push(key);
        }
        
        // profile/all 一次返回全部，不需要分页
        break;
    }
    
    console.log(`📋 作者 ${userId}: 共 ${allIds.length} 个作品`);
    return allIds;
}

/** 从作品列表中统计最频繁的标签 */
async function sampleTagsFromArtworks(userId, artworkIds, sampleCount) {
    const tagFreq = {};
    const n = Math.min(sampleCount || TAG_SAMPLE_COUNT, artworkIds.length);
    if (n === 0) return [];
    
    console.log(`🏷️ 从 ${n} 个作品中采样标签...`);
    const sampleIds = artworkIds.slice(0, n);
    
    for (let i = 0; i < sampleIds.length; i++) {
        const id = sampleIds[i];
        try {
            const info = await getIllustInfo(id);
            if (info && info.tags) {
                for (const tag of info.tags) {
                    if (tag === 'R-18' || tag === 'R-18G') continue;
                    tagFreq[tag] = (tagFreq[tag] || 0) + 1;
                }
            }
        } catch (e) {
            // skip
        }
        if (i < sampleIds.length - 1) await sleep(800);
    }
    
    // 按频率排序
    const sorted = Object.entries(tagFreq)
        .sort((a, b) => b[1] - a[1])
        .map(e => e[0]);
    
    console.log(`🏷️ 采样标签(频率前15): ${sorted.slice(0, 15).map(t => `${t}(${tagFreq[t]})`).join(', ')}`);
    return sorted;
}

/** 构建JSON并下载 */
function downloadJSON(results) {
    const jsonStr = JSON.stringify(results, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    
    let label;
    if (results.mode === 'author') {
        const name = results.author?.name || results.author?.id || 'unknown';
        label = `author_${name}`;
    } else {
        label = IDS.length === 1 ? IDS[0] : `batch_${IDS.length}`;
    }
    
    const a = document.createElement('a');
    a.href = url;
    a.download = `pixiv_${label.replace(/[<>:"/\\|?*]/g, '_')}.json`;
    a.click();
    URL.revokeObjectURL(url);
    
    console.log(`\n💾 JSON文件已下载: ${a.download}`);
    return a.download;
}

// ============ 主流程 ============
(async () => {
    console.log('🚀 Pixiv提取器 v2.0 启动...\n');
    
    const results = {
        mode: '',
        artworks: {},
    };
    
    // === 作者模式 ===
    if (USER_ID && !IDS.length) {
        results.mode = 'author';
        
        // 1. 获取用户信息
        console.log(`👤 获取作者 ${USER_ID} 信息...`);
        const userInfo = await getUserInfo(USER_ID);
        if (!userInfo) {
            console.error('❌ 无法获取作者信息，请检查USER_ID');
            return;
        }
        console.log(`   作者: ${userInfo.name}`);
        
        // 2. 获取profile标签
        console.log(`🔖 获取作者标签...`);
        const profileTags = await getUserProfileTags(USER_ID);
        console.log(`   Profile标签: ${profileTags.join(', ') || '(无)'}`);
        
        // 3. 获取所有作品ID
        const allArtworkIds = await getAllUserIllustIds(USER_ID);
        let artworkIds = allArtworkIds;
        if (MAX_AUTHOR_ARTWORKS > 0) {
            artworkIds = allArtworkIds.slice(0, MAX_AUTHOR_ARTWORKS);
            console.log(`   限制为 ${artworkIds.length} 个作品`);
        }
        
        // 4. 从作品采样标签
        const sampledTags = await sampleTagsFromArtworks(USER_ID, allArtworkIds, TAG_SAMPLE_COUNT);
        
        // 合并标签：profile标签优先，再补采样标签
        const combinedTags = [...new Set([...profileTags, ...sampledTags])];
        
        results.author = {
            id: USER_ID,
            name: userInfo.name,
            tags: combinedTags,
            commentTags: userInfo.commentTags,
            profileTags: profileTags,
            sampledTags: sampledTags,
        };
        
        console.log(`\n📊 作者标签汇总: ${combinedTags.join(', ')}`);
        console.log(`📥 开始获取 ${artworkIds.length} 个作品的URL...\n`);
        
        // 5. 批量获取作品URL (v3: 逐请求延迟, 防止429)
        const DELAY_MS = 800; // 每个请求间隔800ms, 安全速率
        let fetched = 0, skipped = 0, errors = 0;
        const startTime = Date.now();
        for (let i = 0; i < artworkIds.length; i++) {
            const id = artworkIds[i];
            const info = await getIllustInfo(id);
            if (info) {
                results.artworks[id] = {
                    pages: info.pages,
                    title: info.title,
                    ext: info.ext,
                    tags: info.tags,
                    urls: info.urls,
                };
                fetched++;
            } else {
                skipped++;
            }
            if ((i + 1) % 10 === 0 || i === artworkIds.length - 1) {
                const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
                console.log(`  📥 ${i+1}/${artworkIds.length} | ✅${fetched} ⏭${skipped} ❌${errors} | ${elapsed}s`);
            }
            // 每个请求后延迟 (最后一个不延迟)
            if (i < artworkIds.length - 1) await sleep(DELAY_MS);
        }
        
        console.log(`\n✅ 成功 ${fetched}/${artworkIds.length} (跳过${skipped})`);
        
    // === 作品模式 ===
    } else if (IDS.length) {
        results.mode = 'artworks';
        console.log(`📥 批量获取 ${IDS.length} 个作品URL...\n`);
        
        const DELAY_MS = 800;
        let fetched = 0, skipped = 0;
        const startTime = Date.now();
        for (let i = 0; i < IDS.length; i++) {
            const id = IDS[i];
            const info = await getIllustInfo(id);
            if (info) {
                results.artworks[id] = {
                    pages: info.pages,
                    title: info.title,
                    ext: info.ext,
                    tags: info.tags,
                    urls: info.urls,
                };
                fetched++;
            } else {
                skipped++;
            }
            if ((i + 1) % 10 === 0 || i === IDS.length - 1) {
                const elapsed = ((Date.now() - startTime) / 1000).toFixed(0);
                console.log(`  📥 ${i+1}/${IDS.length} | ✅${fetched} ⏭${skipped} | ${elapsed}s`);
            }
            if (i < IDS.length - 1) await sleep(DELAY_MS);
        }
        
        console.log(`\n✅ 成功 ${fetched}/${IDS.length} (跳过${skipped})`);
        
    } else {
        console.error('❌ 请设置 IDS (作品ID数组) 或 USER_ID (作者ID)');
        return;
    }
    
    // 下载JSON
    const filename = downloadJSON(results);
    console.log(`\n📌 下一步: python 下载_核心引擎.py --api-json ${filename}`);
    console.log('   或使用桥接工具: python 下载_从JSON.py --api-json ' + filename);
    
})();
