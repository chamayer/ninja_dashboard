SELECT column_name, is_nullable, column_default, data_type
FROM information_schema.columns
WHERE table_schema='operations' AND table_name='findings'
  AND column_name LIKE 'subject%'
ORDER BY column_name;
