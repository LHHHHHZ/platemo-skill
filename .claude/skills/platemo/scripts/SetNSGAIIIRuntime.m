classdef SetNSGAIIIRuntime < handle
% 临时监测 Python 模型和 MATLAB 注入日志，不改变算法的搜索策略。
    properties (Access = private)
        monitor = []
        randomGuard = []
        logPath
        logOffset = 0
        diagnostics
        localIssues = {}
        injectedBatches = 0
        injectedSolutions = 0
        survivingSolutions = 0
        gaFallbacks = 0
    end
    methods
        function obj = SetNSGAIIIRuntime(params,scriptDir,logPath,seed)
            obj.logPath = logPath;
            mode = 1;
            if ~isempty(params), mode = params{1}; end
            obj.diagnostics = struct('schema_version',1,'adapter','SET_NSGAIII', ...
                'requested_mode',mode,'status','running','python_ready',false, ...
                'cache_reset_calls',0,'model_calls',0,'prediction_attempts',0, ...
                'prediction_successes',0,'prediction_failures',0,'predicted_solutions',0, ...
                'training_steps',0,'models',{{}},'issues',{{}});
            try
                assert(isnumeric(mode) && isscalar(mode) && ismember(mode,[0,1,2]), ...
                    'TRAIN must be 0, 1 or 2.');
                folder = fileparts(which('SET_NSGAIII'));
                pythonPath = fullfile(folder,'.venv','Scripts','python.exe');
                assert(isfile(pythonPath),'Algorithm Python interpreter not found: %s',pythonPath);
                pyenv('Version',pythonPath);
                sys = py.importlib.import_module('sys');
                sys.path.insert(int32(0),folder);
                sys.path.insert(int32(0),scriptDir);
                np = py.importlib.import_module('numpy');
                sp = py.importlib.import_module('scipy');
                torch = py.importlib.import_module('torch');
                if nargin >= 4
                    seedModule = py.importlib.import_module('seed_runtime');
                    assert(strcmpi(char(java.io.File(char(py.getattr(seedModule,'__file__'))).getCanonicalPath()), ...
                        char(java.io.File(fullfile(scriptDir,'seed_runtime.py')).getCanonicalPath())), ...
                        'Seed controller was imported from a different skill directory.');
                    seedModule = py.importlib.reload(seedModule);
                    obj.randomGuard = seedModule.RandomStateGuard(torch,int64(seed));
                    obj.diagnostics.randomness = jsondecode(char(obj.randomGuard.info_json()));
                end
                module = py.importlib.import_module('SetTransformer');
                adapter = py.importlib.import_module('set_nsgaiii_runtime');
                assert(strcmpi(char(java.io.File(char(py.getattr(module,'__file__'))).getCanonicalPath()), ...
                    char(java.io.File(fullfile(folder,'SetTransformer.py')).getCanonicalPath())), ...
                    'SetTransformer was imported from a different algorithm directory.');
                assert(strcmpi(char(java.io.File(char(py.getattr(adapter,'__file__'))).getCanonicalPath()), ...
                    char(java.io.File(fullfile(scriptDir,'set_nsgaiii_runtime.py')).getCanonicalPath())), ...
                    'Runtime adapter was imported from a different skill directory.');
                % 重载当前磁盘源码，避免同一 MATLAB 进程复用旧模型代码。
                if logical(py.hasattr(module,'_platemo_runtime_monitor'))
                    previous = py.getattr(module,'_platemo_runtime_monitor');
                    previous.close();
                end
                module = py.importlib.reload(module);
                adapter = py.importlib.reload(adapter);
                obj.monitor = adapter.start(module,int32(mode));
                obj.diagnostics.environment = struct('python',char(sys.version), ...
                    'executable',char(sys.executable),'numpy',char(py.getattr(np,'__version__')), ...
                    'scipy',char(py.getattr(sp,'__version__')),'torch',char(py.getattr(torch,'__version__')));
            catch ME
                obj.addIssue('dependency_preflight_failed',ME.message);
            end
        end
        function ensurePreflight(obj)
            assert(isempty(obj.localIssues),'PlatEMO:SurrogateInvalid', ...
                'SET_NSGAIII dependency preflight failed. See runtime diagnostics.');
        end
        function diag = check(obj,final)
            diag = obj.report(final);
            if ~isempty(diag.issues)
                error('PlatEMO:SurrogateInvalid','SET_NSGAIII runtime verification failed: %s', ...
                    diag.issues{1}.message);
            end
        end
        function diag = report(obj,final)
            obj.readLog();
            diag = obj.diagnostics;
            if ~isempty(obj.monitor)
                current = jsondecode(char(obj.monitor.snapshot_json()));
                names = fieldnames(current);
                for i = 1:numel(names), diag.(names{i}) = current.(names{i}); end
            end
            diag.models = obj.asCells(diag.models);
            diag.issues = [obj.asCells(diag.issues),obj.localIssues];
            diag.python_ready = diag.cache_reset_calls > 0;
            diag.injected_batches = obj.injectedBatches;
            diag.injected_solutions = obj.injectedSolutions;
            diag.surviving_solutions = obj.survivingSolutions;
            diag.ga_fallbacks = obj.gaFallbacks;
            diag.log = obj.logPath;
            if ~final && isempty(diag.issues) && ~diag.python_ready
                diag.issues{end+1} = struct('code','surrogate_initialization_unconfirmed', ...
                    'message','Algorithm did not complete the monitored Python initialization.');
            end
            if ~isempty(diag.issues)
                diag.status = 'failed';
            elseif final && (diag.prediction_successes < 1 || diag.injected_solutions < 1)
                diag.status = 'not_exercised';
                diag.issues{end+1} = struct('code','surrogate_not_exercised','message', ...
                    'No successful MATLAB prediction injection. Check maxFE, N, GW and prediction interval.');
            elseif final && ismember(diag.requested_mode,[1,2]) && diag.training_steps < 1
                diag.status = 'not_exercised';
                diag.issues{end+1} = struct('code','training_not_exercised','message', ...
                    'Requested online training did not execute any training step. Check GW and history windows.');
            elseif final
                diag.status = 'passed';
            else
                diag.status = 'running';
            end
        end
        function close(obj)
            if ~isempty(obj.monitor)
                obj.monitor.close();
                obj.monitor = [];
            end
            if ~isempty(obj.randomGuard)
                obj.randomGuard.close();
                obj.randomGuard = [];
            end
        end
        function delete(obj)
            obj.close();
        end
    end
    methods (Access = private)
        function addIssue(obj,code,message)
            obj.localIssues{end+1} = struct('code',code,'message',message);
        end
        function readLog(obj)
            % 刷新 diary 并增量读取，避免每一代重复扫描整份日志。
            diary off;
            fid = fopen(obj.logPath,'rb');
            if fid < 0
                diary(obj.logPath);
                obj.addIssue('runtime_log_unreadable','Cannot read per-run runtime log.');
                return;
            end
            fseek(fid,obj.logOffset,'bof');
            chunk = char(fread(fid,inf,'*uint8')');
            obj.logOffset = ftell(fid);
            fclose(fid);
            diary(obj.logPath);
            failed = strfind(chunk,'Warning: Set Transformer failed at generation');
            if contains(chunk,'Warning: Python surrogate initialization failed:')
                obj.addIssue('python_initialization_failed','Algorithm reported Python initialization failure.');
            end
            if ~isempty(failed)
                obj.gaFallbacks = obj.gaFallbacks + numel(failed);
                obj.addIssue('matlab_prediction_failed','Algorithm reported prediction failure and GA fallback.');
            end
            tokens = regexp(chunk,'\[PredStats\] gen \d+ \| pred survive (\d+)/(\d+)','tokens');
            for i = 1:numel(tokens)
                count = str2double(tokens{i}{2});
                if count > 0
                    obj.injectedBatches = obj.injectedBatches + 1;
                    obj.injectedSolutions = obj.injectedSolutions + count;
                    obj.survivingSolutions = obj.survivingSolutions + str2double(tokens{i}{1});
                end
            end
        end
    end
    methods (Static, Access = private)
        function cells = asCells(value)
            if iscell(value), cells = value(:)'; else, cells = num2cell(value(:)'); end
        end
    end
end
