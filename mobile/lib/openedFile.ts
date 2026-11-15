/** The app's OpenedStore, in a JSON file in the app's document directory. */
import { File, Paths } from 'expo-file-system';

import { OpenedStore } from './opened';

const file = new File(Paths.document, 'opened-incidents.json');

export const openedStore = new OpenedStore({
  read: () => (file.exists ? file.textSync() : null),
  write: (text) => {
    if (!file.exists) file.create();
    void file.write(text);
  },
});
