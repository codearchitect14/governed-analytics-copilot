import type { ComponentProps } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import ReactCore from "echarts-for-react/lib/core";

echarts.use([BarChart, LineChart, PieChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer]);

type Props = Omit<ComponentProps<typeof ReactCore>, "echarts">;

export default function ReactECharts(props: Props) {
  return <ReactCore echarts={echarts} {...props} />;
}
