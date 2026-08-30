import Card from './ui/Card';
import Badge from './ui/Badge';

interface Props {
  title: string;
  description: string;
  features: string[];
}

export default function PagePlaceholder({ title, description, features }: Props) {
  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-xl font-bold text-primary-900">{title}</h1>
        <Badge variant="info">规划中</Badge>
      </div>
      <Card>
        <p className="text-text-secondary mb-4">{description}</p>
        <ul className="space-y-2 text-sm text-text-secondary">
          {features.map((f) => (
            <li key={f}>• {f}</li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
