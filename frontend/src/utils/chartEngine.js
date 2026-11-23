import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, ScatterChart, HeatmapChart, RadarChart, FunnelChart, GaugeChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, GridComponent, LegendComponent, VisualMapComponent, DataZoomComponent, MarkLineComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { LabelLayout } from 'echarts/features'

echarts.use([
  BarChart, LineChart, PieChart, ScatterChart, HeatmapChart, RadarChart, FunnelChart, GaugeChart,
  TitleComponent, TooltipComponent, GridComponent, LegendComponent, VisualMapComponent,
  DataZoomComponent, MarkLineComponent, CanvasRenderer, LabelLayout,
])

export { echarts }
