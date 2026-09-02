import { useState } from 'react';
import Button from '../components/ui/Button';
import { saveProfile, type Profile } from '../services/api';

interface Question {
  key: keyof Omit<Profile, 'onboarded'>;
  title: string;
  options: string[];
  multi?: boolean;
}

const QUESTIONS: Question[] = [
  { key: 'risk_tolerance', title: '您的风险偏好？', options: ['保守型', '稳健型', '激进型'] },
  { key: 'invest_amount', title: '您的可投资金额大约是？', options: ['10万以下', '10-50万', '50-100万', '100万以上'] },
  { key: 'markets', title: '您主要交易哪些市场？（可多选）', options: ['A股', '港股', '美股'], multi: true },
  { key: 'holding_period', title: '您偏好的持仓周期？', options: ['日内交易', '数天~数周', '数月以上'] },
  { key: 'experience', title: '您的投资经验？', options: ['新手', '有经验', '资深'] },
];

export default function Onboarding({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string | string[]>>({});
  const [saving, setSaving] = useState(false);
  const [errMsg, setErrMsg] = useState('');

  const q = QUESTIONS[step];
  const current = (answers[q.key] ?? (q.multi ? [] : '')) as string | string[];

  const select = (opt: string) => {
    if (q.multi) {
      const arr = [...(current as string[])];
      const i = arr.indexOf(opt);
      if (i >= 0) arr.splice(i, 1); else arr.push(opt);
      setAnswers({ ...answers, [q.key]: arr });
    } else {
      setAnswers({ ...answers, [q.key]: opt });
    }
  };

  const isSelected = (opt: string) =>
    q.multi ? (current as string[]).includes(opt) : current === opt;

  const canNext = q.multi ? (current as string[]).length > 0 : current !== '';

  const finish = async () => {
    setSaving(true);
    setErrMsg('');
    try {
      const res = await saveProfile({
        risk_tolerance: String(answers.risk_tolerance ?? '稳健型'),
        invest_amount: String(answers.invest_amount ?? '10-50万'),
        markets: (answers.markets as string[]) || ['A股'],
        holding_period: String(answers.holding_period ?? '数天~数周'),
        experience: String(answers.experience ?? '有经验'),
      });
      if (res.ok) {
        onDone();
        return;
      }
      setErrMsg('保存失败：' + (res.error || '未知错误，请稍后重试'));
    } catch (e) {
      setErrMsg('保存失败：' + (e instanceof Error ? e.message : String(e)));
    }
    setSaving(false);
  };

  return (
    <div className="min-h-screen bg-primary-50 flex items-center justify-center">
      <div className="bg-surface rounded-xl shadow-lg p-10 w-[560px]">
        <div className="text-center mb-8">
          <div className="text-3xl mb-2">📈</div>
          <h1 className="text-xl font-bold text-primary-900">欢迎使用 AI 投资分析</h1>
          <p className="text-sm text-text-secondary mt-2">完成以下问卷，AI 将为您提供更贴合的投资建议（可在设置中随时修改）</p>
        </div>
        <div className="flex gap-1.5 mb-6">
          {QUESTIONS.map((_, i) => (
            <div key={i} className={`h-1.5 flex-1 rounded-full ${i <= step ? 'bg-primary-500' : 'bg-primary-100'}`} />
          ))}
        </div>
        <h2 className="font-bold mb-4">{step + 1}. {q.title}</h2>
        <div className="space-y-2 mb-8">
          {q.options.map((opt) => (
            <button
              key={opt}
              onClick={() => select(opt)}
              className={`w-full text-left px-4 py-3 rounded-lg border text-sm transition-colors ${
                isSelected(opt) ? 'border-primary-500 bg-primary-50 text-primary-700 font-medium' : 'border-border hover:border-primary-300'
              }`}
            >
              {q.multi && <span className="mr-2">{isSelected(opt) ? '☑' : '☐'}</span>}
              {opt}
            </button>
          ))}
        </div>
        {errMsg && <p className="text-xs text-danger mb-3">{errMsg}</p>}
        <div className="flex justify-between">
          <Button variant="secondary" onClick={() => setStep(Math.max(0, step - 1))} disabled={step === 0 || saving}>上一步</Button>
          {step < QUESTIONS.length - 1 ? (
            <Button onClick={() => canNext && setStep(step + 1)} disabled={!canNext}>下一步</Button>
          ) : (
            <Button onClick={finish} disabled={!canNext || saving}>{saving ? '保存中...' : '开始使用'}</Button>
          )}
        </div>
      </div>
    </div>
  );
}
