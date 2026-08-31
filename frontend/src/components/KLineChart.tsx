// ECharts K 线图组件：蜡烛图 + MA5/MA10/MA20 均线 + RSI14 副图（S9 自选股看板）
import { useEffect, useRef } from 'react';
import * as echarts from 'echarts';
import type { KlineBar } from '../services/api';

interface Props {
  bars: KlineBar[];
  height?: number;
}

/** 简单移动平均：前 period-1 个点为 null */
function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    out.push(i >= period - 1 ? sum / period : null);
  }
  return out;
}

/** RSI(14)：Wilder 平滑，前 14 个点为 null */
function rsi14(closes: number[]): (number | null)[] {
  const out: (number | null)[] = [null];
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i < closes.length; i++) {
    const diff = closes[i] - closes[i - 1];
    const gain = Math.max(diff, 0);
    const loss = Math.max(-diff, 0);
    if (i <= 14) {
      avgGain += gain / 14;
      avgLoss += loss / 14;
      out.push(i === 14 ? (avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss)) : null);
    } else {
      avgGain = (avgGain * 13 + gain) / 14;
      avgLoss = (avgLoss * 13 + loss) / 14;
      out.push(avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss));
    }
  }
  return out;
}

export default function KLineChart({ bars, height = 420 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  // 初始化 + 自适应尺寸
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = echarts.init(el);
    chartRef.current = chart;
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(el);
    return () => {
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  // 数据更新
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || bars.length === 0) return;
    const dates = bars.map((b) => b.date);
    const closes = bars.map((b) => b.close);
    const ma5 = sma(closes, 5);
    const ma10 = sma(closes, 10);
    const ma20 = sma(closes, 20);
    const rsi = rsi14(closes);
    const klineData = bars.map((b) => [b.open, b.close, b.low, b.high]);

    chart.setOption({
      animation: false,
      backgroundColor: 'transparent',
      axisPointer: {
        link: [{ xAxisIndex: 'all' }],
        label: { backgroundColor: '#3A7CC3' },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'cross' },
      },
      legend: {
        data: ['MA5', 'MA10', 'MA20', 'RSI14'],
        top: 0,
        itemWidth: 14,
        itemHeight: 8,
        textStyle: { color: '#6B7280', fontSize: 11 },
      },
      grid: [
        { left: 56, right: 16, top: 28, height: '56%' },
        { left: 56, right: 16, top: '73%', height: '17%' },
      ],
      xAxis: [
        {
          type: 'category',
          data: dates,
          gridIndex: 0,
          boundaryGap: true,
          axisLine: { lineStyle: { color: '#E4E7ED' } },
          axisLabel: { color: '#9CA3AF', fontSize: 10 },
          axisTick: { show: false },
        },
        {
          type: 'category',
          data: dates,
          gridIndex: 1,
          axisLine: { lineStyle: { color: '#E4E7ED' } },
          axisLabel: { show: false },
          axisTick: { show: false },
        },
      ],
      yAxis: [
        {
          scale: true,
          gridIndex: 0,
          position: 'left',
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: '#9CA3AF', fontSize: 10 },
          splitLine: { lineStyle: { color: '#E4E7ED' } },
        },
        {
          scale: true,
          gridIndex: 1,
          min: 0,
          max: 100,
          splitNumber: 2,
          axisLine: { show: false },
          axisTick: { show: false },
          axisLabel: { color: '#9CA3AF', fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      dataZoom: [
        { type: 'inside', xAxisIndex: [0, 1], start: 55, end: 100 },
        { type: 'slider', xAxisIndex: [0, 1], bottom: 4, height: 16, start: 55, end: 100, borderColor: '#E4E7ED' },
      ],
      series: [
        {
          name: 'K线',
          type: 'candlestick',
          data: klineData,
          itemStyle: {
            color: '#FF4D4F',
            color0: '#52C41A',
            borderColor: '#FF4D4F',
            borderColor0: '#52C41A',
          },
        },
        {
          name: 'MA5',
          type: 'line',
          data: ma5,
          showSymbol: false,
          smooth: true,
          lineStyle: { width: 1 },
          itemStyle: { color: '#F59E0B' },
        },
        {
          name: 'MA10',
          type: 'line',
          data: ma10,
          showSymbol: false,
          smooth: true,
          lineStyle: { width: 1 },
          itemStyle: { color: '#3A7CC3' },
        },
        {
          name: 'MA20',
          type: 'line',
          data: ma20,
          showSymbol: false,
          smooth: true,
          lineStyle: { width: 1 },
          itemStyle: { color: '#8B5CF6' },
        },
        {
          name: 'RSI14',
          type: 'line',
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: rsi,
          showSymbol: false,
          smooth: true,
          lineStyle: { width: 1 },
          itemStyle: { color: '#FA8C16' },
        },
      ],
    } as echarts.EChartsOption);
  }, [bars]);

  return <div ref={ref} style={{ width: '100%', height }} />;
}
