// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

// removed external GitHub link
import { useTranslations } from "next-intl";

import { AuroraText } from "~/components/magicui/aurora-text";
import { Button } from "~/components/ui/button";

import { SectionHeader } from "../components/section-header";

export function JoinCommunitySection() {
  const t = useTranslations("landing.joinCommunity");
  return (
    <section className="flex w-full flex-col items-center justify-center pb-12">
      <SectionHeader
        anchor="join-community"
        title={
          <AuroraText colors={["#60A5FA", "#A5FA60", "#A560FA"]}>
            {t("title")}
          </AuroraText>
        }
        description={t("description")}
      />
      {/* 私有化部署：移除社区贡献外链 */}
    </section>
  );
}
