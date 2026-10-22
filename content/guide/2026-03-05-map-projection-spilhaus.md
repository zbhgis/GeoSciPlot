---
title: "顶刊中的全球地图投影（四）-Spilhaus投影Python实现"
date: "2026-03-05"
categoryTags: ["科研"]
subCategoryTags: ["科研地图", "地图投影"]
---
# 顶刊中的全球地图投影（四）-Spilhaus投影Python实现

点击上方“**浩瀚地学**”关注并设为**星标**，可及时获取最新推送。多多**点赞转发**，一起学习进步。若有问题也欢迎在留言区中交流与指正。

# 前言

之前的文章介绍了一些地图投影的Python简单实现，这篇将会进一步对Spilhaus投影进行补充，帮助大家能够绘制出预期中的地图投影效果。

完整代码及数据均开源，获取方式见文末。

# Spilhaus投影

## Spilhaus投影是什么

以下图片来源：https://doi.org/10.1126/sciadv.ady6314

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202603090835929.png)

## Spilhaus投影的海陆边界

直接绘制Spilhaus投影，海陆边界并不明显，也就是难以突出海洋部分，因此可以直接使用Natural Earth提供的海陆边界数据，就陆地部分设置为白色或者透明即可（或者自行添加矢量数据也可以）。

这个代码绘制的结果相较于之前，海洋部分就明显了许多。

spilhaus.py

```Python
"""
-------------------------------------------------------------------------------
@Author         :  zbhgis
@Github         :  https://github.com/zbhgis
@Description    :  spilhaus without basemap
-------------------------------------------------------------------------------
"""

import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature


fig = plt.figure(figsize=(10, 10), dpi=100)
ax = fig.add_subplot(1, 1, 1, projection=ccrs.Spilhaus())
ax.set_global()
ax.add_feature(cfeature.OCEAN, facecolor="#1f77b4", zorder=0)
ax.add_feature(cfeature.LAND, facecolor="none", edgecolor="none", zorder=1)
ax.coastlines(resolution="50m", color="black")
ax.gridlines(draw_labels=True, linestyle="--")

title = "spilhaus_nobasemap"
plt.title(title)
plt.savefig(
    f"./fig_res/{title}.png",
    dpi=100,
    bbox_inches="tight",
)
print("ok")

```

打印结果

```Plain
ok
```

绘制结果

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202603090835677.png)

## Spilhaus投影的海洋底图

Spilhaus投影海洋部分是主体，一般底图是蓝色系或蓝色渐变色。除了像上面的代码直接填充蓝色，也可以使用自定义地图或者数据作为海洋底图。

代码中以dem数据为例，在上述代码的基础上进行改进，设置了一个自定义蓝色渐变色带来渲染DEM数据，作为海洋底图。添加数据的逻辑与之前的代码类似。

spilhaus2.py

```Python
"""
-------------------------------------------------------------------------------
@Author         :  zbhgis
@Github         :  https://github.com/zbhgis
@Description    :  spilhaus with gradient blue basemap
-------------------------------------------------------------------------------
"""

import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import rasterio
import matplotlib.colors as mcolors


plt.rcParams["font.family"] = "Arial"
dem_tif = "./data_res/gebco_dem.tif"
fig = plt.figure(figsize=(10, 10), dpi=100)
ax = fig.add_subplot(1, 1, 1, projection=ccrs.Spilhaus())
ax.set_global()
ax.add_feature(cfeature.LAND, facecolor="white", edgecolor="none", zorder=1)
ax.coastlines(resolution="50m", color="black")
ax.gridlines(draw_labels=True, linestyle="--")

# 自定义色带
ocean_colors = [
    "#f4fdfe",
    "#c4edfa",
    "#94dff6",
    "#63cbee",
    "#4a91cb",
    "#2f56a9",
    "#17208b",
    "#0a017a",
    "#0b007a",
    "#0c075f",
]
custom_cmap = mcolors.LinearSegmentedColormap.from_list(
    "custom_ocean", ocean_colors, N=256
)

with rasterio.open(dem_tif) as src:
    dem_data = src.read(1, masked=True)
    dem_data = -dem_data
    left, bottom, right, top = src.bounds
    extent = [left, right, bottom, top]

    im = ax.imshow(
        dem_data,
        extent=extent,
        transform=ccrs.PlateCarree(),
        origin="upper",
        cmap=custom_cmap,
        vmin=0,
        vmax=8000,
        alpha=0.8,
        interpolation="bilinear",
        zorder=0,
    )

# 添加DEM色带
cbar = fig.colorbar(
    im,
    ax=ax,
    orientation="horizontal",
    pad=0.04,
    aspect=40,
    shrink=0.6,
    extend="max",
)
cbar.set_ticks([0, 2000, 4000, 6000, 8000])
cbar.set_ticklabels(["0", "2", "4", "6", "8"])
cbar.ax.tick_params(
    labelsize=16,
    labelcolor="black",
    length=0,
)
cbar.set_label("Depth (km)", fontsize=18)

# 添加标题并保存
title = "spilhaus_dem"
plt.title(title, fontsize=20)
plt.savefig(
    f"./fig_res/{title}.png",
    dpi=100,
    bbox_inches="tight",
)
print("ok")

```

打印结果

```Plain
ok
```

绘制结果

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202603090835940.png)

# 写在最后

完整代码及相关数据文件会在以下github仓库中开源，若有帮助欢迎点个star，不胜感激。

https://github.com/zbhgis/Projects

或者在微信公众号后台回复关键词“**代码获取**”即可获取百度网盘链接，找到对应名称的文件夹即可（百度网盘链接可能隔几天才会同步）。

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202603090835620.jpeg)

代码中使用了很多相对路径，建议获取的时候下载完整文件夹。

该系列下一篇会再对Orthographic投影绘制进行补充。

如有问题，欢迎添加个人微信交流。