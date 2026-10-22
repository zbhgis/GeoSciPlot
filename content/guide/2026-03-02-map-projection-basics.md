---
title: "顶刊中的全球地图投影（一）-常用投影"
date: "2026-03-02"
categoryTags: ["科研"]
subCategoryTags: ["科研地图", "地图投影"]
---
# 顶刊中的全球地图投影（一）-常用投影

点击上方“**浩瀚地学**”关注并设为**星标**，可及时获取最新推送。多多**点赞转发**，一起学习进步。若有问题也欢迎在留言区中交流与指正。

# 前言

花时间整理了一些世界地图投影与代码复现，以及顶刊中对应的地图。这篇文章先简单地介绍一下常用地图投影的区别，特点，作图参考，以及各自的用途。

# 地图投影的区别

以下是常用的地图投影的主要区别

**圆柱与伪圆柱投影的异同：**

圆柱（Cylindrical）投影的经线全部为直线且平行，形成矩形地图网格，导致高纬极端扭曲，如Mercator、Behrmann等；

伪圆柱（Pseudocylindrical）投影的经线除中央直线外均为对称弯曲曲线，整体变形更均匀自然，为椭圆或圆润桶形，如Robinson、Mollweide等。

**等角，等积，折衷投影的异同：**

等角 (Conformal）投影保留局部角度和形状准确，但牺牲面积，导致高纬严重夸大，如Mercato等；

等积（Equal-Area）投影保留相对面积比例正确，形状不够准确，如Equal Earth等；

折衷（Compromise）投影则在面积、形状、角度间寻求平衡以最小化整体畸变，无单一属性完美保留，但视觉最自然，如Robinson等。

# 常用地图投影汇总

以下地图投影比如Mercator，Hammer等只是一类投影的简称，他们在自身的投影基础上会有很多衍生投影，比如Mercator投影是正轴等角圆柱投影，其衍生投影有Web Mercator（比如网页中的瓦片地图）和Transverse Mercator（比如UTM分带系统）等。具体不同投影的差别可以在以下网站查询对比或者直接问AI大模型。

https://map-projections.net/projections-list.php

接下来是整理的7个常用的全球地图投影（没有进行客观的数据统计，仅仅是结合经验和部分搜索结果得出）。

| 名称                                                   | 类型            | 属性 | 主要特点                                                     |
| ------------------------------------------------------ | --------------- | ---- | ------------------------------------------------------------ |
| Mercator / Mercator Cylindrical                        | 圆柱            | 等角 | 保持角度/形状准确，航海经典；但高纬度面积严重夸大            |
| Robinson / Robinson Pseudocylindrical                  | 伪圆柱          | 折衷 | 视觉平衡好，对于面积和形状均有取舍                           |
| Equal Earth / Equal Earth Equal-Area Pseudocylindrical | 伪圆柱          | 等积 | 形状类似Robinson但严格等积，美观且面积准确                   |
| Mollweide / Mollweide Equal-Area                       | 伪圆柱 (椭圆形) | 等积 | 椭圆形（2:1轴比），压缩极区，面积准确                        |
| Eckert IV / Eckert IV Equal-Area Pseudocylindrical     | 伪圆柱          | 等积 | 侧边经线半圆，拐角平滑，面积准确                             |
| Behrmann / Behrmann Equal-Area Cylindrical             | 圆柱            | 等积 | 标准纬线±30°，压缩极区，面积准确                             |
| Hammer / Hammer Equal-Area / Hammer-Aitoff             | 伪圆柱 (椭圆形) | 等积 | 类似Mollweide但更圆润，面积精确；适合小比例全球地图，扭曲较均匀 |

# 顶刊地图投影参考

整理了Nature和Science系列期刊（主要是Nature系列）上的对应投影的一些地图的呈现结果，供各位参考。

## Mercator

**示例1**

期刊：Nature Ecology & Evolution

来源：https://doi.org/10.1038/s41559-025-02955-6

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280835474.png)

**示例2**

期刊：Nature

来源：https://doi.org/10.1038/s41586-022-05413-6

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280835278.png)

## Robinson

**示例1**

期刊：Nature Communications

来源：https://doi.org/10.1038/s41467-023-37027-5

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280835579.png)

**示例2**

期刊：Nature Ecology & Evolution

来源：https://doi.org/10.1038/s41559-023-02071-3

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280835364.png)

## Equal Earth

**示例1**

期刊：Nature Communications

来源：https://doi.org/10.1038/s41467-025-57054-8

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280835037.png)

**示例1**

期刊：Nature Communications

来源：https://doi.org/10.1038/s41467-025-64449-0

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280833218.png)

## Mollweide

**示例1**

期刊：Nature

来源：https://doi.org/10.1038/s41586-021-03371-z

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280833043.png)

**示例2**

期刊：Nature Climate Change

来源：https://doi.org/10.1038/s41558-025-02498-5

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280836357.png)

## Eckert IV

**示例1**

期刊：Nature Climate Change

来源：https://doi.org/10.1038/s41558-025-02337-7

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280833247.png)

**示例2**

期刊：Nature Ecology & Evolution

来源：https://doi.org/10.1038/s41559-024-02599-y

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280836166.png)

## Behrmann

**示例1**

期刊：Nature Communications

来源：https://doi.org/10.1038/s41467-021-27186-8

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280836784.png)

**示例2**

期刊：Nature Ecology & Evolution

来源：https://doi.org/10.1038/s41559-024-02450-4

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280836432.png)

## Hammer

**示例1**

期刊：Nature Climate Change

来源：https://doi.org/10.1038/nclimate2554

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280833484.png)

**示例2**

期刊：Nature Astronomy

来源：https://doi.org/10.1038/s41550-023-02130-6

图片：

![img](https://cdn.jsdelivr.net/gh/zbhgis/BlogImg@main/blog/202602280833624.png)

# 不同投影的用途

这些投影在样本点展示的时候基本都能用，但是Robinson折衷投影在视觉上最为协调，所以主要在展示研究区或者样点的时候使用；而在全球数据处理的时候，投影可能会导致同一地区的面积在数据中相差较大，所以在数据处理的时候，主要使用Equal Earth，Mollweide这些等面积的投影，减少偏差；至于等面积投影之间具体选择哪个，笔者认为没有太大差别，很多时候是根据手上的数据投影再进一步选择；Hammer投影貌似是在天文领域用得比较多，所以也一并整理。

# 写在最后

“顶刊全球地图投影”系列会更新4~8篇，主要内容是不同地图投影的基本介绍，绘图参考，以及实现方法。

下一篇会介绍一些特殊的全球地图投影。