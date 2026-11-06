SELECT title
FROM `bigquery-public-data.stackoverflow.posts_questions`
WHERE LOWER(title) LIKE 'how%'
  AND REGEXP_CONTAINS(CONCAT('|', tags, '|'), r'\|(android-layout|android-activity|android-intent|android-edittext|android-fragments|android-recyclerview|android-listview|android-asynctask|android-sqlite|android-studio|android-gradle-plugin|android-view|android-service|android-broadcastreceiver|android-contentprovider|android-xml)\|')
ORDER BY view_count DESC
LIMIT 1